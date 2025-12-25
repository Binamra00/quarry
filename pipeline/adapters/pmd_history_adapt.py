import json
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

        # [SWE CONFIG] Checkpoint Interval
        # Balance between Performance (High Interval) and Safety (Low Interval)
        # 10 means we write to disk only once every 10 commits.
        self.checkpoint_interval = 10

        # [ORGANIZATION] Define a dedicated subfolder for raw batch files
        self.raw_output_dir = config.OUTPUTS_PATH / "pmd_raw" / self.target_repo_path.name
        if not self.raw_output_dir.exists():
            self.raw_output_dir.mkdir(parents=True, exist_ok=True)

    def get_tool_name(self) -> str:
        return f"PMD History (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        # This file is now used as the execution log
        return config.OUTPUTS_PATH / f"pmd_history_execution_{self.target_repo_path.name}.log"

    def _get_commit_list(self) -> List[str]:
        # Silence this check too
        cmd = ["git", "rev-list", "HEAD", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        if success and output:
            return output.strip().split('\n')
        return []

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        # [FIX] Pre-Flight Check (Softened)
        # Instead of failing immediately, we warn the user.
        status_success, status_out = adapter_subprocess.run_command(
            ["git", "status", "--porcelain"],
            cwd=str(self.target_repo_path),
            verbose=False
        )
        if status_success and status_out.strip():
            print("⚠️  WARNING: Repository has uncommitted changes.")
            print("   Time-travel requires a clean state. Changes might be stashed or lost.")
            print("   Proceeding in 3 seconds... (Ctrl+C to abort)")
            import time
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
        print(f"   📝 Detailed execution log: {log_path.name}")

        success_count = 0
        skipped_count = 0
        ruleset_path = config.PMD_RULESET_PATH

        # [REFACTOR] Use the new encapsulated getter
        batch_start_index = self.state_manager.get_next_start_index()

        # [LOGGING] Open log file in Append mode to preserve history across batches
        with open(log_path, "a") as log_file:
            log_file.write(
                f"\n\n--- Batch Execution Start: {len(batch)} commits (Indices {batch_start_index}-{batch_start_index + len(batch)}) ---\n")

            try:
                for i, commit_hash in enumerate(batch):
                    global_index = batch_start_index + i

                    # [SWE LOGIC] Checkpointing Strategy
                    # Only write to disk if it's a checkpoint OR the very last item in batch
                    is_last_in_batch = (i == len(batch) - 1)
                    should_flush = ((i + 1) % self.checkpoint_interval == 0) or is_last_in_batch

                    # [UI] Update Progress Bar (Console)
                    ui_strategy.update_progress(i + 1, len(batch), prefix=f"   ⏳ Batch [{commit_hash[:7]}]:")

                    # [LOG] Write intent to file
                    log_file.write(f"\n[COMMIT {commit_hash}] ----------------\n")

                    commit_output_path = self.raw_output_dir / f"pmd_out_{commit_hash}.json"

                    if commit_output_path.exists() and commit_output_path.stat().st_size > 0:
                        try:
                            with open(commit_output_path, 'r') as f:
                                json.load(f)
                            # [FIX] Lazy Flush: pass calculated boolean
                            self.state_manager.save_progress(commit_hash, global_index, total_commits,
                                                             flush=should_flush)
                            skipped_count += 1
                            log_file.write("Skipped (Output exists)\n")
                            continue
                        except json.JSONDecodeError:
                            log_file.write("Output corrupt. Re-running.\n")

                    # A. Time Travel (Quiet Mode)
                    log_file.write(f"[EXEC] git checkout -f {commit_hash}\n")
                    checkout_cmd = ["git", "checkout", "-f", commit_hash]
                    checkout_success, checkout_out = adapter_subprocess.run_command(
                        checkout_cmd,
                        cwd=str(self.target_repo_path),
                        verbose=False
                    )

                    if not checkout_success:
                        error_msg = f"Checkout failed: {checkout_out}\n"
                        log_file.write(error_msg)
                        ui_strategy.clear_line()
                        print(f"   ⚠️ Checkout failed for {commit_hash}. Check logs.")

                        # [FIX] Lazy Flush: pass calculated boolean
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)
                        continue

                    # B. Run PMD (Quiet Mode)
                    log_file.write(f"[EXEC] pmd check ...\n")
                    pmd_cmd = [
                        str(config.PMD_PATH), "check",
                        "-d", str(self.target_repo_path),
                        "-R", str(ruleset_path),
                        "-f", "json",
                        "-r", str(commit_output_path),
                        "--no-cache"
                    ]

                    pmd_success, pmd_out = adapter_subprocess.run_command(
                        pmd_cmd,
                        allowed_exit_codes=[0, 4],
                        verbose=False
                    )

                    # C. Update State
                    if pmd_success:
                        success_count += 1
                        log_file.write("PMD Success\n")
                    else:
                        log_file.write(f"PMD Failed: {pmd_out}\n")

                    # [FIX] Lazy Flush: pass calculated boolean
                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)

                # [SAFETY] Ensure final flush happens at end of loop (redundant but safe)
                self.state_manager.flush()

            finally:
                ui_strategy.clear_line()
                print(f"   🔙 Restoring branch: {current_branch}...")
                adapter_subprocess.run_command(
                    ["git", "checkout", "-f", current_branch],
                    cwd=str(self.target_repo_path),
                    verbose=False
                )
                # [SAFETY] Double ensure flush happens if loop crashes
                self.state_manager.flush()

        print(f"✅ Batch Complete. Processed {success_count} new, Skipped {skipped_count} existing.")
        return True