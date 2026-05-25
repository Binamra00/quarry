import json
import re
import time
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.batch_state import BatchStateManager
from pipeline.adapters.i_adapters import IAdapter

try:
    from pydriller import Repository
except ImportError:
    Repository = None


class LedgerAdapter(IAdapter):
    """
    Stateful Adapter for Evolutionary Ledger Mining (using PyDriller).
    Strategy: 'Graph Traversal Batching' with JSONL Streaming.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "ledger")
        self.checkpoint_interval_seconds = 300

        # Heuristic to detect bug fixes based on commit messages
        self.bug_pattern = re.compile(
            r'\b(bug|fix|issue|error|resolve|patch|defect|crash)\b',
            re.IGNORECASE
        )

        self.jsonl_output_path = config.OUTPUTS_PATH / f"ledger_history_{self.target_repo_path.name}.jsonl"

    def get_tool_name(self) -> str:
        return f"Evolutionary Ledger (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"ledger_execution_{self.target_repo_path.name}.log"

    def _get_commit_batch(self) -> List[str]:
        """Retrieves the next batch of chronological commits to process."""
        cmd = ["git", "rev-list", "HEAD", "--reverse"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)

        if not success or not output or not output.strip():
            return []

        all_commits = output.strip().split('\n')
        total_commits = len(all_commits)
        next_start = self.state_manager.get_next_start_index()

        if next_start >= total_commits:
            return []

        return all_commits[next_start: next_start + self.batch_size]

    def _get_total_commit_count(self) -> int:
        cmd = ["git", "rev-list", "--count", "HEAD"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        return int(output.strip()) if success and output and output.strip() else 0

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        if Repository is None:
            print("❌ Error: 'pydriller' is not installed. Please check your requirements.txt.")
            return False

        total_commits = self._get_total_commit_count()
        if total_commits == 0:
            print("❌ No commits found to analyze.")
            return False

        batch = self._get_commit_batch()

        if not batch:
            print(f"✅ Analysis already complete for all {total_commits} commits.")
            return True

        print(f"   📊 Batch Scope: {len(batch)} commits")

        log_path = self.get_output_path()
        last_checkpoint_time = time.time()
        success_count = 0
        batch_start_index = self.state_manager.get_next_start_index()

        with open(log_path, "a", encoding="utf-8") as log_file:
            try:
                # PyDriller Optimization: Pass the exact batch of SHAs.
                # PyDriller reads the internal Git Tree directly (No checkouts required!)
                repo_miner = Repository(str(self.target_repo_path), only_commits=batch)

                for i, commit in enumerate(repo_miner.traverse_commits()):
                    global_index = batch_start_index + i
                    commit_hash = commit.hash

                    ui_strategy.update_progress(
                        global_index + 1,
                        total_commits,
                        prefix=f"   📖 Scanning [{commit_hash[:7]}]"
                    )

                    # 1. Check Idempotency
                    if self.state_manager.is_commit_processed(commit_hash):
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=False)
                        continue

                    # 2. Extract Socio-Technical Metadata
                    record = {
                        "sha": commit_hash,
                        "timestamp": int(commit.committer_date.timestamp()),
                        "author_name": commit.author.name,
                        "author_email": commit.author.email, # [FIX] Added email for precise identity resolution
                        "is_bug_fix": bool(self.bug_pattern.search(commit.msg)),
                        "modifications": []
                    }

                    # 3. Extract File-Level Churn (Java files only)
                    for mod in commit.modified_files:
                        if mod.filename.endswith('.java'):
                            raw_path = mod.new_path or mod.old_path
                            if not raw_path:
                                continue

                            clean_rel_path = str(raw_path).replace('\\', '/')
                            universal_path = clean_rel_path

                            # [FIX] Capture the old path securely if this is a RENAME event
                            old_universal_path = None
                            if mod.old_path and mod.change_type.name == "RENAME":
                                old_clean_rel = str(mod.old_path).replace('\\', '/')
                                old_universal_path = old_clean_rel

                            record["modifications"].append({
                                "file": universal_path,
                                "old_file": old_universal_path, # [FIX] Added old_file
                                "lines_added": mod.added_lines,
                                "lines_deleted": mod.deleted_lines,
                                "change_type": mod.change_type.name
                            })

                    # 4. Stream to JSONL
                    try:
                        with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                            jsonl_file.write(json.dumps(record) + "\n")
                        success_count += 1
                    except Exception as e:
                        log_file.write(f"[CRITICAL] Could not write ledger to JSONL: {e}\n")

                    # 5. Update State
                    current_time = time.time()
                    should_flush = (current_time - last_checkpoint_time >= self.checkpoint_interval_seconds) or (
                                i == len(batch) - 1)

                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)

                    if should_flush:
                        last_checkpoint_time = current_time

            except KeyboardInterrupt:
                print("\n⚠️  Interrupt detected! Saving progress...")
                self.state_manager.flush()
                return False

            except Exception as e:
                print(f"\n❌ [CRITICAL] PyDriller Crash: {e}")
                log_file.write(f"[CRITICAL] PyDriller Crash: {e}\n")
                self.state_manager.flush()
                return False

            finally:
                ui_strategy.clear_line()
                self.state_manager.flush()

        # --- UX: Detailed Batch Summary ---
        total_processed_so_far = batch_start_index + len(batch)
        remaining = max(0, total_commits - total_processed_so_far)
        print(f"✅ Batch Complete. Scanned {total_processed_so_far}/{total_commits} | Remaining: {remaining}")

        if success_count > 0:
            print(f"   📈 Extracted ledger events for {success_count} commits.")

        return True