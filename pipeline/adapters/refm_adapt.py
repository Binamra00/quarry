import json
import os
import time
import subprocess
import tempfile
import uuid
import shutil
from pathlib import Path
from typing import List, Set

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.adapters.i_adapter import IAdapter


class RefactoringMinerAdapter(IAdapter):
    """
    Adapter for RefactoringMiner.
    Uses 'JSONL Streaming' for O(1) memory usage and instant persistence.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = None):
        super().__init__(target_repo_path)
        # Checkpoint interval is less relevant with streaming,
        # but we keep it if we want to log periodic status updates.
        self.checkpoint_interval_seconds = 300

    def get_tool_name(self) -> str:
        return "RefactoringMiner (History Mining)"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        # [CHANGE] Use .jsonl for streaming support
        return config.OUTPUTS_PATH / f"refactorings_{project_name}.jsonl"

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

    def _get_processed_shas(self) -> Set[str]:
        """
        Scans the existing JSONL file line-by-line to find already processed commits.
        Memory Usage: O(M) where M is the number of SHAs (very small strings),
        NOT O(Data Size).
        """
        output_path = self.get_output_path()
        processed = set()

        if not output_path.exists():
            return processed

        print(f"   🔍 Scanning existing log: {output_path.name}...")
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        # Lightweight parse: just check if valid JSON and extract SHA
                        record = json.loads(line)
                        if "sha1" in record:
                            processed.add(record["sha1"])
                    except json.JSONDecodeError:
                        # Skip corrupt lines (resilience)
                        continue
        except Exception as e:
            print(f"   ⚠️ Warning reading existing log: {e}")

        return processed

    def _get_lib_path(self) -> Path:
        """
        Robustly resolves the 'lib' directory containing JAR dependencies.
        """
        if not shutil.which("java"):
            raise RuntimeError("'java' executable not found in system PATH.")

        rm_executable = Path(config.RM_PATH)

        # Candidate 1: Standard dist
        candidate_standard = rm_executable.parent.parent / "lib"
        # Candidate 2: Flat dist
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
        print(f"--- ⚡ Starting {self.get_tool_name()} [Streaming Mode] ---")

        try:
            lib_dir = self._get_lib_path()
            java_classpath = str(lib_dir / "*")
        except (FileNotFoundError, RuntimeError) as e:
            print(f"❌ Error: Configuration failed: {e}")
            return False

        all_commits = self._get_all_commits()
        if not all_commits:
            print("❌ Error: No commits found.")
            return False

        # [CHANGE] Streaming State Recovery
        processed_shas = self._get_processed_shas()
        remaining_commits = [sha for sha in all_commits if sha not in processed_shas]

        if not remaining_commits:
            print(f"✅ Analysis already complete ({len(processed_shas)} commits).")
            return True

        print(
            f"   🔄 Resuming: Found {len(processed_shas)} existing. Processing {len(remaining_commits)} new commits...")

        log_path = self.get_log_path()
        new_commits_count = 0

        # Prepare Environment
        env = os.environ.copy()

        # [CHANGE] Open file in APPEND mode ("a") and keep it open
        # We use buffering=1 for line-buffered writing (flushes on newline)
        with open(self.get_output_path(), "a", encoding="utf-8", buffering=1) as stream_file, \
                open(log_path, "a", encoding="utf-8") as log_file:

            try:
                for i, commit_hash in enumerate(remaining_commits):
                    ui_strategy.update_progress(i + 1, len(remaining_commits),
                                                prefix=f"   ⛏️  Mining [{commit_hash[:7]}]")

                    unique_id = uuid.uuid4().hex[:8]
                    temp_json_file = Path(tempfile.gettempdir()) / f"rm_{commit_hash}_{unique_id}.json"

                    # Prepare the Record Object
                    record = {
                        "repository": str(self.target_repo_path),
                        "sha1": commit_hash,
                        "refactorings": []  # Default empty
                    }

                    try:
                        cmd = [
                            "java",
                            "-cp", java_classpath,
                            config.RM_ENTRY_POINT_CLASS,
                            "-c", str(self.target_repo_path),
                            commit_hash,
                            "-json", str(temp_json_file)
                        ]

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

                        # Parse Output
                        valid_data_found = False
                        if temp_json_file.exists() and temp_json_file.stat().st_size > 0:
                            try:
                                with open(temp_json_file, 'r', encoding='utf-8') as f:
                                    tool_output = json.load(f)

                                # RefactoringMiner output format handling
                                if tool_output:
                                    if "commits" in tool_output and tool_output["commits"]:
                                        # It returns a list, but we only asked for one commit
                                        record["refactorings"] = tool_output["commits"][0].get("refactorings", [])
                                        valid_data_found = True
                                    elif "refactorings" in tool_output:
                                        record["refactorings"] = tool_output["refactorings"]
                                        valid_data_found = True

                            except json.JSONDecodeError:
                                log_file.write(f"\n[ERROR] Corrupt JSON in temp file for {commit_hash}\n")

                        if not valid_data_found:
                            if result.returncode != 0:
                                log_file.write(
                                    f"\n[FAILURE] Tool crashed for {commit_hash}. Exit: {result.returncode}\n")
                            else:
                                # Normal case for commits with no refactorings
                                pass

                                # [CRITICAL CHANGE] Write to Stream Immediately
                        stream_file.write(json.dumps(record) + "\n")
                        # stream_file.flush() # buffering=1 handles this, but explicit flush is safer if paranoid

                        new_commits_count += 1

                    finally:
                        # Cleanup Temp File
                        if temp_json_file.exists():
                            try:
                                temp_json_file.unlink()
                            except OSError:
                                pass  # Best effort cleanup

            except KeyboardInterrupt:
                print("\n⚠️  Interrupt detected! Output stream saved safely.")
                return False

        print(f"✅ Success. Streamed {new_commits_count} commits to {self.get_output_path().name}")
        return True