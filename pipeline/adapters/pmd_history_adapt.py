import sys
import json
import subprocess
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.batch_state import BatchStateManager
from pipeline.adapters.i_adapter import IAdapter


class PMDHistoryAdapter(IAdapter):
    """
    Stateful Adapter for PMD.
    Strategy: 'Time-Travel Batching' with Buffered I/O.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "pmd_history")

        # [ORGANIZATION] Define a dedicated subfolder for raw batch files
        self.raw_output_dir = config.OUTPUTS_PATH / "pmd_raw" / self.target_repo_path.name
        if not self.raw_output_dir.exists():
            self.raw_output_dir.mkdir(parents=True, exist_ok=True)

    def get_tool_name(self) -> str:
        return f"PMD History (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"pmd_history_batch_log_{self.target_repo_path.name}.json"

    def _get_commit_list(self) -> List[str]:
        cmd = ["git", "rev-list", "HEAD", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path))
        if success and output:
            return output.strip().split('\n')
        return []

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        # Pre-Flight Check
        status_success, status_out = adapter_subprocess.run_command(
            ["git", "status", "--porcelain"],
            cwd=str(self.target_repo_path)
        )
        if status_success and status_out.strip():
            print("❌ CRITICAL: Repository has uncommitted changes.")
            return False

        all_commits = self._get_commit_list()
        total_commits = len(all_commits)
        if total_commits == 0:
            print("❌ No commits found.")
            return False

        batch = self.state_manager.get_next_batch(all_commits, self.batch_size)
        if not batch:
            print("✅ Analysis already complete.")
            return True

        current_branch = "main"
        success, output = adapter_subprocess.run_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(self.target_repo_path)
        )
        if success and output:
            current_branch = output.strip()

        print(f"   🚀 Processing Batch: {len(batch)} commits")

        success_count = 0
        skipped_count = 0
        ruleset_path = config.PMD_RULESET_PATH

        # [BUG FIX] Capture the base index ONCE before the loop starts
        batch_start_index = self.state_manager.state["last_index"] + 1

        try:
            for i, commit_hash in enumerate(batch):
                # [BUG FIX] Calculate global index relative to the batch start
                global_index = batch_start_index + i

                ui_strategy.update_progress(i + 1, len(batch), prefix=f"   ⏳ Batch [{commit_hash[:7]}]:")

                # [ORGANIZATION] Save to subfolder
                commit_output_path = self.raw_output_dir / f"pmd_out_{commit_hash}.json"

                if commit_output_path.exists() and commit_output_path.stat().st_size > 0:
                    try:
                        with open(commit_output_path, 'r') as f:
                            json.load(f)

                        # [LAZY PERSISTENCE] Update memory, skip I/O
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=False)
                        skipped_count += 1
                        continue
                    except json.JSONDecodeError:
                        pass  # File corrupt, re-run

                # A. Time Travel
                checkout_cmd = ["git", "checkout", "-f", commit_hash]
                checkout_success, _ = adapter_subprocess.run_command(checkout_cmd, cwd=str(self.target_repo_path))

                if not checkout_success:
                    print(f"\n   ⚠️ Critical: Checkout failed for {commit_hash}. Marking as processed to skip.")
                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=True)
                    continue

                # B. Run PMD
                pmd_cmd = [
                    str(config.PMD_PATH), "check",
                    "-d", str(self.target_repo_path),
                    "-R", str(ruleset_path),
                    "-f", "json",
                    "-r", str(commit_output_path),
                    "--no-cache"
                ]

                pmd_success, _ = adapter_subprocess.run_command(pmd_cmd, allowed_exit_codes=[0, 4])

                # C. Update State
                if pmd_success:
                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=True)
                    success_count += 1
                else:
                    print(f"\n   ⚠️ PMD Failed on commit {commit_hash}. Marking processed to avoid retry loop.")
                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=True)

            # [FINAL SYNC] Flush buffer
            self.state_manager.flush()

        finally:
            ui_strategy.clear_line()
            print(f"   🔙 Restoring branch: {current_branch}...")
            adapter_subprocess.run_command(["git", "checkout", "-f", current_branch], cwd=str(self.target_repo_path))

        print(f"✅ Batch Complete. Processed {success_count} new, Skipped {skipped_count} existing.")
        return True