import json
import os
import time
import subprocess
import tempfile
import uuid
import shutil
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.adapters.i_adapter import IAdapter


class RefactoringMinerAdapter(IAdapter):
    """
    Adapter for RefactoringMiner.
    Uses 'Stateful Batching' and Centralized Configuration.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = None):
        super().__init__(target_repo_path)
        self.checkpoint_interval_seconds = 300

    def get_tool_name(self) -> str:
        return "RefactoringMiner (History Mining)"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"refactorings_{project_name}.json"

    def _get_all_commits(self) -> List[str]:
        cmd = ["git", "rev-list", "HEAD", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(
            cmd,
            cwd=str(self.target_repo_path),
            verbose=False
        )
        if success and output:
            return output.strip().split('\n')
        return []

    def _load_existing_results(self) -> List[dict]:
        output_path = self.get_output_path()
        if output_path.exists():
            try:
                with open(output_path, 'r') as f:
                    data = json.load(f)
                    return data.get("commits", [])
            except json.JSONDecodeError:
                print("   ⚠️ Existing output corrupt. Starting fresh.")
        return []

    def _get_lib_path(self) -> Path:
        """
        Robustly resolves the 'lib' directory containing JAR dependencies.
        """
        # 1. Pre-flight Check: Ensure Java is actually available
        if not shutil.which("java"):
            raise RuntimeError("'java' executable not found in system PATH.")

        rm_executable = Path(config.RM_PATH)

        # Candidate 1: Standard dist (root/bin/RefactoringMiner.bat -> lib is in root/lib)
        candidate_standard = rm_executable.parent.parent / "lib"

        # Candidate 2: Flat dist (bin and lib in same folder)
        candidate_flat = rm_executable.parent / "lib"

        if candidate_standard.exists() and candidate_standard.is_dir():
            return candidate_standard
        elif candidate_flat.exists() and candidate_flat.is_dir():
            return candidate_flat

        raise FileNotFoundError(
            f"Critical: Could not locate 'lib' directory for RefactoringMiner.\n"
            f"Checked:\n1. {candidate_standard}\n2. {candidate_flat}"
        )

    def execute(self) -> bool:
        print(f"--- ⚡ Starting {self.get_tool_name()} ---")

        try:
            lib_dir = self._get_lib_path()
            java_classpath = str(lib_dir / "*")
        except (FileNotFoundError, RuntimeError) as e:
            print(f"❌ Error: Configuration failed: {e}")
            return False

        all_commits = self._get_all_commits()
        total_commits = len(all_commits)
        if total_commits == 0:
            print("❌ Error: No commits found.")
            return False

        existing_data = self._load_existing_results()

        processed_shas = {
            c.get('sha1')
            for c in existing_data
            if isinstance(c, dict) and c.get('sha1') is not None
        }

        remaining_commits = [sha for sha in all_commits if sha not in processed_shas]

        if not remaining_commits:
            print(f"✅ Analysis already complete ({len(existing_data)} commits).")
            return True

        print(f"   🔄 Resuming: Found {len(existing_data)} existing. Processing {len(remaining_commits)} new commits...")

        current_data = existing_data
        new_commits_count = 0
        log_path = self.get_log_path()
        last_checkpoint_time = time.time()

        env = os.environ.copy()

        with open(log_path, "a") as log_file:
            try:
                for i, commit_hash in enumerate(remaining_commits):
                    ui_strategy.update_progress(i + 1, len(remaining_commits),
                                                prefix=f"   ⛏️  Mining [{commit_hash[:7]}]")

                    unique_id = uuid.uuid4().hex[:8]
                    temp_json_file = Path(tempfile.gettempdir()) / f"rm_{commit_hash}_{unique_id}.json"

                    try:
                        # [Windows Fix] Invoke Java directly with wildcard classpath
                        # This bypasses the 8191-character command line limit on Windows
                        cmd = [
                            "java",
                            "-cp", java_classpath,
                            config.RM_ENTRY_POINT_CLASS,
                            "-c", str(self.target_repo_path),
                            commit_hash,
                            "-json", str(temp_json_file)
                        ]

                        # Log sample command (first only) to avoid log file bloat on large histories
                        if i == 0:
                            log_file.write(f"\n[DEBUG] Java Command (Sample): {' '.join(cmd)}\n")

                        result = subprocess.run(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                            env=env
                        )

                        # ... (JSON Parsing logic remains identical) ...
                        valid_data_found = False
                        if temp_json_file.exists() and temp_json_file.stat().st_size > 0:
                            try:
                                with open(temp_json_file, 'r') as f:
                                    commit_data = json.load(f)
                                if commit_data:
                                    if "commits" in commit_data:
                                        current_data.extend(commit_data["commits"])
                                        valid_data_found = True
                                    elif "refactorings" in commit_data:
                                        if "sha1" in commit_data:
                                            current_data.append(commit_data)
                                        else:
                                            current_data.append({
                                                "repository": str(self.target_repo_path),
                                                "sha1": commit_hash,
                                                "refactorings": commit_data.get("refactorings", [])
                                            })
                                        valid_data_found = True
                            except json.JSONDecodeError:
                                log_file.write(f"\n[ERROR] Corrupt JSON in temp file for {commit_hash}\n")

                        if valid_data_found:
                            new_commits_count += 1
                        else:
                            if result.returncode != 0:
                                log_file.write(
                                    f"\n[FAILURE] Tool crashed for {commit_hash}. Exit: {result.returncode}\n")
                                log_file.write(f"STDERR: {result.stderr.strip()}\n")
                            else:
                                log_file.write(f"\n[INFO] No JSON file generated for {commit_hash}.\n")

                            current_data.append({
                                "repository": str(self.target_repo_path),
                                "sha1": commit_hash,
                                "refactorings": []
                            })
                            new_commits_count += 1

                    finally:
                        # [Config Usage] Use centralized retry settings for consistent behavior
                        if temp_json_file.exists():
                            for attempt in range(config.IO_MAX_RETRIES):
                                try:
                                    temp_json_file.unlink()
                                    break
                                except (OSError, PermissionError) as e:
                                    if attempt == config.IO_MAX_RETRIES - 1:
                                        log_file.write(
                                            f"\n[WARN] Failed to delete temp file {temp_json_file.name}: {e}\n"
                                        )
                                    else:
                                        delay = min(1.0, config.IO_RETRY_DELAY_BASE * (2 ** attempt))
                                        time.sleep(delay)

                    current_time = time.time()
                    time_diff = current_time - last_checkpoint_time
                    is_last = (i == len(remaining_commits) - 1)

                    if time_diff >= self.checkpoint_interval_seconds or is_last:
                        self._flush_to_disk(current_data, log_file)
                        last_checkpoint_time = current_time

            except KeyboardInterrupt:
                print("\n⚠️  Interrupt detected! Saving progress...")
                self._flush_to_disk(current_data, log_file)
                return False

        print(f"✅ Success. Added {new_commits_count} new commits. Total: {len(current_data)}")
        return True

    def _flush_to_disk(self, data: List[dict], log_file=None):
        if not data: return
        output_path = self.get_output_path()
        temp_path = output_path.with_suffix(".tmp")
        try:
            with open(temp_path, 'w') as f:
                json.dump({"commits": data}, f, indent=2)
            os.replace(temp_path, output_path)
            if log_file:
                log_file.write(f"\n[CHECKPOINT] Saved {len(data)} commits.\n")
        except Exception as e:
            msg = f"   ❌ Save failed: {e}"
            print(msg)
            if log_file:
                log_file.write(f"\n[ERROR] {msg}\n")