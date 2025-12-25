import json
import time
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
    Strategy: 'Time-Travel Batching' with Time-Based Checkpointing.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "pmd_history")
        self.checkpoint_interval_seconds = 300
        self.raw_output_dir = config.OUTPUTS_PATH / "pmd_raw" / self.target_repo_path.name
        if not self.raw_output_dir.exists():
            self.raw_output_dir.mkdir(parents=True, exist_ok=True)

    def get_tool_name(self) -> str:
        return f"PMD History (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"pmd_history_execution_{self.target_repo_path.name}.log"

    def _get_commit_list(self) -> List[str]:
        cmd = ["git", "rev-list", "HEAD", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        if success and output:
            return output.strip().split('\n')
        return []

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        status_success, status_out = adapter_subprocess.run_command(
            ["git", "status", "--porcelain"],
            cwd=str(self.target_repo_path),
            verbose=False
        )
        if status_success and status_out.strip():
            print("⚠️  WARNING: Repository has uncommitted changes.")
            time.sleep(3)

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
            cwd=str(self.target_repo_path),
            verbose=False
        )
        if success and output:
            current_branch = output.strip()

        print(f"   🚀 Processing Batch: {len(batch)} commits")
        log_path = self.get_output_path()

        success_count = 0
        skipped_count = 0
        ruleset_path = config.PMD_RULESET_PATH
        batch_start_index = self.state_manager.get_next_start_index()
        last_checkpoint_time = time.time()

        with open(log_path, "a") as log_file:
            log_file.write(
                f"\n\n--- Batch Execution Start: {len(batch)} commits (Indices {batch_start_index}-{batch_start_index + len(batch)}) ---\n")

            try:
                for i, commit_hash in enumerate(batch):
                    global_index = batch_start_index + i

                    # [LOGIC] Determine flush need
                    current_time = time.time()
                    time_diff = current_time - last_checkpoint_time
                    time_based_flush = time_diff >= self.checkpoint_interval_seconds
                    is_last_in_batch = (i == len(batch) - 1)
                    should_flush = time_based_flush or is_last_in_batch

                    ui_strategy.update_progress(i + 1, len(batch), prefix=f"   ⏳ Batch [{commit_hash[:7]}]:")
                    log_file.write(f"\n[COMMIT {commit_hash}] ----------------\n")

                    commit_output_path = self.raw_output_dir / f"pmd_out_{commit_hash}.json"

                    if commit_output_path.exists() and commit_output_path.stat().st_size > 0:
                        try:
                            with open(commit_output_path, 'r') as f:
                                json.load(f)
                            self.state_manager.save_progress(commit_hash, global_index, total_commits,
                                                             flush=should_flush)
                            skipped_count += 1
                            log_file.write("Skipped (Output exists)\n")
                            # [FIX] Update timer if we flush, even on skip
                            if should_flush: last_checkpoint_time = current_time
                            continue
                        except json.JSONDecodeError:
                            log_file.write("Output corrupt. Re-running.\n")

                    log_file.write(f"[EXEC] git checkout -f {commit_hash}\n")
                    checkout_success, checkout_out = adapter_subprocess.run_command(
                        ["git", "checkout", "-f", commit_hash],
                        cwd=str(self.target_repo_path),
                        verbose=False
                    )

                    if not checkout_success:
                        # [FIX] Clean log formatting and increment count
                        log_file.write(f"Checkout failed: {checkout_out.strip()}\n")
                        skipped_count += 1
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)
                        if should_flush: last_checkpoint_time = current_time
                        continue

                    log_file.write(f"[EXEC] pmd check ...\n")
                    pmd_cmd = [str(config.PMD_PATH), "check", "-d", str(self.target_repo_path), "-R", str(ruleset_path),
                               "-f", "json", "-r", str(commit_output_path), "--no-cache"]
                    pmd_success, pmd_out = adapter_subprocess.run_command(pmd_cmd, allowed_exit_codes=[0, 4],
                                                                          verbose=False)

                    if pmd_success:
                        success_count += 1
                        log_file.write("PMD Success\n")
                    else:
                        log_file.write(f"PMD Failed: {pmd_out}\n")

                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)

                    # [FIX] Reset timer only after successful flush cycle
                    if should_flush:
                        last_checkpoint_time = current_time

                self.state_manager.flush()

            finally:
                ui_strategy.clear_line()
                print(f"   🔙 Restoring branch: {current_branch}...")
                adapter_subprocess.run_command(["git", "checkout", "-f", current_branch],
                                               cwd=str(self.target_repo_path), verbose=False)
                self.state_manager.flush()

        print(f"✅ Batch Complete. Processed {success_count} new, Skipped {skipped_count} existing.")
        return True