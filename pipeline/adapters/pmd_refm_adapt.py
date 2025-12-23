import sys
import subprocess
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.batch_state import BatchStateManager
from pipeline.adapters.i_adapter import IAdapter


class PMDRefmAdapter(IAdapter):
    """
    Stateful Adapter for PMD.
    Strategy: 'Time-Travel Batching'
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "pmd_history")

    def get_tool_name(self) -> str:
        return f"PMD History (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH

    def _get_commit_list(self) -> List[str]:
        """Retrieves the full production history (Main Branch Only)."""
        cmd = ["git", "rev-list", "HEAD", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path))

        if success and output:
            return output.strip().split('\n')
        return []

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        # 1. Get Full History
        all_commits = self._get_commit_list()
        total_commits = len(all_commits)

        if total_commits == 0:
            print("❌ No commits found.")
            return False

        # 2. Ask the Manager for the next batch
        # [USE CONFIG] Use the injected batch_size
        batch = self.state_manager.get_next_batch(all_commits, self.batch_size)

        if not batch:
            print("✅ Analysis already complete (State file indicates 100% done).")
            return True

        # 3. The Time-Travel Loop
        print(f"   🚀 Processing Batch: {len(batch)} commits")

        success_count = 0
        ruleset_path = config.PMD_RULESET_PATH

        for i, commit_hash in enumerate(batch):
            global_index = self.state_manager.state["last_index"] + 1 + i
            ui_strategy.update_progress(i + 1, len(batch), prefix=f"   ⏳ Batch [{commit_hash[:7]}]:")

            # A. Time Travel
            checkout_cmd = ["git", "checkout", "-f", commit_hash]
            adapter_subprocess.run_command(checkout_cmd, cwd=str(self.target_repo_path))

            # B. Run PMD
            commit_output_path = config.OUTPUTS_PATH / f"pmd_out_{commit_hash}.json"

            if commit_output_path.exists() and commit_output_path.stat().st_size > 0:
                self.state_manager.save_progress(commit_hash, global_index, total_commits)
                continue

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
                self.state_manager.save_progress(commit_hash, global_index, total_commits)
                success_count += 1
            else:
                print(f"\n   ⚠️ PMD Failed on commit {commit_hash}. Skipping update.")

        ui_strategy.clear_line()

        # 4. Teardown
        print("   🔙 Returning to main branch...")
        adapter_subprocess.run_command(["git", "checkout", "-f", "main"], cwd=str(self.target_repo_path))

        print(f"✅ Batch Complete. Processed {success_count}/{len(batch)} commits.")
        return True