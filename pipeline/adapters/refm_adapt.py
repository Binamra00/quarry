import json
import os
import time
import subprocess
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.json_parser import StackBasedJsonParser
from pipeline.adapters.i_adapter import IAdapter


class RefactoringMinerAdapter(IAdapter):
    """
    Adapter for RefactoringMiner v3.0.
    Strategy: 'Stateful Batching' with Deterministic Stream Parsing.
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

    def execute(self) -> bool:
        print(f"--- ⚡ Starting {self.get_tool_name()} ---")

        all_commits = self._get_all_commits()
        total_commits = len(all_commits)
        if total_commits == 0:
            print("❌ No commits found.")
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

        with open(log_path, "a") as log_file:
            try:
                for i, commit_hash in enumerate(remaining_commits):
                    ui_strategy.update_progress(i + 1, len(remaining_commits),
                                                prefix=f"   ⛏️  Mining [{commit_hash[:7]}]")

                    cmd = [str(config.RM_PATH), "-c", str(self.target_repo_path), commit_hash]

                    result = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False
                    )

                    commit_data = StackBasedJsonParser.extract_json(result.stdout)

                    valid_data_found = False

                    if commit_data:
                        if "commits" in commit_data:
                            current_data.extend(commit_data["commits"])
                            valid_data_found = True
                        elif "refactorings" in commit_data:
                            # [CO-PILOT FIX] Ensure integrity before appending
                            if "sha1" in commit_data:
                                current_data.append(commit_data)
                                valid_data_found = True
                            else:
                                # Reconstruct missing metadata if RM drops it
                                current_data.append({
                                    "repository": str(self.target_repo_path),
                                    "sha1": commit_hash,
                                    "refactorings": commit_data.get("refactorings", [])
                                })
                                valid_data_found = True

                    if valid_data_found:
                        new_commits_count += 1
                    else:
                        if result.returncode != 0:
                            log_file.write(f"\n[FAILURE] Exit Code {result.returncode} for {commit_hash}.\n")

                        # Fallback: Record empty entry
                        current_data.append({
                            "repository": str(self.target_repo_path),
                            "sha1": commit_hash,
                            "refactorings": []
                        })
                        new_commits_count += 1

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