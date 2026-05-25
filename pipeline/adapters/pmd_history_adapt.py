import json
import time
import tempfile
import uuid
import re
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.batch_state import BatchStateManager
from pipeline.adapters.i_adapters import IAdapter


# ==========================================
# CONSTANTS (Module Level)
# ==========================================
# Pre-compiled patterns for performance
# Matches: "The method 'foo' has a cyclomatic complexity of 10."
CC_PATTERN = re.compile(r'complexity of (\d+)')
# Matches: "The method 'foo' has an NCSS line count of 50."
NCSS_PATTERN = re.compile(r'line count of (\d+)')


class PMDHistoryAdapter(IAdapter):
    """
    Stateful Adapter for PMD.
    Strategy: 'Time-Travel Batching' with JSONL Streaming (Scalable).
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "pmd_history")
        self.checkpoint_interval_seconds = 300
        # Sampling State: Stores the set of interesting SHAs
        self.sampling_filter = None

        # Output to a single JSONL file instead of a directory
        self.jsonl_output_path = config.OUTPUTS_PATH / f"pmd_history_{self.target_repo_path.name}.jsonl"

    def set_sampling_filter(self, sampled_shas: set):
        """[OVERRIDE] Configure the adapter to skip uninteresting commits and isolate data."""
        self.sampling_filter = sampled_shas

        # [FIX] Isolate the data streams so full-runs and sampled-runs don't contaminate each other
        sampled_prefix = "pmd_sampled"

        # 1. Reroute the JSONL data stream
        self.jsonl_output_path = config.OUTPUTS_PATH / f"{sampled_prefix}_metrics_{self.target_repo_path.name}.jsonl"

        # 2. Re-initialize a brand new State Manager pointing to a different memory file
        self.state_manager = BatchStateManager(self.target_repo_path.name, sampled_prefix)

        print(f"   🎯 Adapter Strategy Update: Filtering for {len(self.sampling_filter)} specific commits.")
        print(f"   📂 Redirecting data stream to: {self.jsonl_output_path.name}")

    def get_tool_name(self) -> str:
        mode = "Sampled " if self.sampling_filter else ""
        return f"PMD History ({mode}Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        mode = "sampled_" if self.sampling_filter else ""
        return config.OUTPUTS_PATH / f"pmd_history_execution_{mode}{self.target_repo_path.name}.log"

    def _get_commit_batch(self) -> List[str]:
        """Retrieves the next chronological batch of commits."""

        # [FIX] If we are sampling specific tags, they might be on older release
        # branches not reachable from the current HEAD (e.g., v1.x vs v3.x).
        # We must use '--all' to ensure we capture and sort every requested SHA.
        if self.sampling_filter:
            cmd = ["git", "rev-list", "--all", "--reverse"]
        else:
            # For standard contiguous mining, we stick to HEAD to avoid
            # double-counting abandoned pull requests and orphan branches.
            cmd = ["git", "rev-list", "HEAD", "--reverse"]

        success, output = adapter_subprocess.run_command(
            cmd, cwd=str(self.target_repo_path), verbose=False
        )

        if not success or not output or not output.strip():
            return []

        all_commits_ordered = output.strip().split('\n')

        # If sampling, preserve chronological order by filtering the ordered list
        if self.sampling_filter:
            ordered_targets = [sha for sha in all_commits_ordered if sha in self.sampling_filter]
            next_start = self.state_manager.get_next_start_index()
            if next_start >= len(ordered_targets):
                return []
            return ordered_targets[next_start: next_start + self.batch_size]

        # Standard full-history batching
        total_commits = len(all_commits_ordered)
        next_start = self.state_manager.get_next_start_index()
        if next_start >= total_commits:
            return []
        return all_commits_ordered[next_start: next_start + self.batch_size]

    def _get_total_commit_count(self) -> int:
        cmd = ["git", "rev-list", "--count", "HEAD"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        # [FIX] Ensure output is not empty/whitespace before converting to int
        return int(output.strip()) if success and output and output.strip() else 0

    def _extract_metric_score(self, rule_name: str, message: str) -> int:
        """
        Internal Utility: Extracts raw numeric scores from PMD messages.
        Returns 0 if no score is found.
        """
        match = None
        if "CyclomaticComplexity" in rule_name:
            match = CC_PATTERN.search(message)
        elif "NcssCount" in rule_name:
            match = NCSS_PATTERN.search(message)

        if match:
            return int(match.group(1))
        return 0

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        # [FIX] Set the total work based on strategy
        if self.sampling_filter:
            total_commits = len(self.sampling_filter)
        else:
            total_commits = self._get_total_commit_count()

        if total_commits == 0:
            # Added a clear error message here for better UX
            print("❌ No commits found to analyze.")
            return False

        # [REMOVED REDUNDANT VERIFICATION LINE]

        batch = self._get_commit_batch()

        if not batch:
            print(f"✅ Analysis already complete for all {total_commits} commits.")
            return True

        print(f"   📊 Batch Scope: {len(batch)} commits")

        # Robustly save the starting state (supports detached HEAD for version-pinned runs)
        success, start_state = adapter_subprocess.run_command(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.target_repo_path),
            verbose=False
        )
        start_state = start_state.strip() if success else "main"

        log_path = self.get_output_path()
        last_checkpoint_time = time.time()
        success_count = 0

        # Use configured PMD ruleset path from config
        ruleset_path = config.PMD_RULESET_PATH

        # Fail-Fast: Verify ruleset exists before processing commits
        if not Path(ruleset_path).exists():
            print(f"❌ Ruleset not found at: {ruleset_path}")
            return False

        # Calculate start index ONCE before loop to prevent drift
        batch_start_index = self.state_manager.get_next_start_index()

        with open(log_path, "a",encoding="utf-8") as log_file:
            try:
                for i, commit_hash in enumerate(batch):
                    global_index = batch_start_index + i

                    ui_strategy.update_progress(
                        global_index + 1,
                        total_commits,
                        prefix=f"   🔄 Processing [{commit_hash[:7]}]"
                    )

                    # 2. Check if already processed (Idempotency)
                    if self.state_manager.is_commit_processed(commit_hash):
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=False)
                        # NOTE: Commits in the state manager are skipped.
                        # No new JSONL record is written for them to preserve append-only history.
                        continue

                    # 3. Time Travel & Clean
                    # FIRST: Destroy any untracked files/directories from the previous era
                    clean_cmd = ["git", "clean", "-fdx"]
                    adapter_subprocess.run_command(clean_cmd, cwd=str(self.target_repo_path), verbose=False)

                    # THEN: Checkout the new target state
                    checkout_cmd = ["git", "checkout", "-f", commit_hash]
                    checkout_success, _ = adapter_subprocess.run_command(checkout_cmd,
                                                                         cwd=str(self.target_repo_path),
                                                                         verbose=False)

                    if not checkout_success:
                        # [FIX] Changed FATAL to ERROR as execution continues
                        log_file.write(f"[ERROR] Could not checkout {commit_hash}. Skipping run.\n")

                        # Emit a JSONL record for this failed checkout to keep data consistent
                        try:
                            status_record = {
                                "sha": commit_hash,
                                "timestamp": int(time.time()),
                                "status": "checkout_failed",
                                "violations": []
                            }
                            with open(self.jsonl_output_path, "a",encoding="utf-8") as jsonl_file:
                                jsonl_file.write(json.dumps(status_record) + "\n")
                        except Exception as e:
                            log_file.write(f"[WARN] Failed to write checkout_failed record to JSONL: {e}\n")

                        # Mark as processed to prevent retry/infinite loops on this commit
                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=False)
                        continue

                    # 4. Run PMD (Isolated Temp File)
                    unique_id = uuid.uuid4().hex[:8]
                    temp_json_path = Path(tempfile.gettempdir()) / f"pmd_{commit_hash}_{unique_id}.json"

                    pmd_cmd = [
                        str(config.PMD_PATH), "check",
                        "-d", str(self.target_repo_path),
                        "-R", str(ruleset_path),
                        "-f", "json",
                        "-r", str(temp_json_path),
                        "--no-cache",
                        "--no-progress"
                    ]

                    # [FIX] Removed redundant 'run_status = pending' initialization
                    # Initialize violation data container
                    violation_data = []
                    run_status = "pending"

                    try:
                        pmd_success, pmd_out = adapter_subprocess.run_command(
                            pmd_cmd,
                            allowed_exit_codes=[0, 4],
                            verbose=False,
                            timeout=300
                        )

                        # 5. Capture Data
                        # [FIX] We removed 'pmd_success' from this check.
                        # If the file exists and has content, we process it regardless of exit code/console noise.
                        if temp_json_path.exists() and temp_json_path.stat().st_size > 0:
                            try:
                                with open(temp_json_path, 'r', encoding='utf-8') as temp_file:  # Added utf-8 safety
                                    raw_json = json.load(temp_file)
                                    violation_data = raw_json.get("files", [])

                                    # [NEW] Enriched Logic for Revealed Preference
                                    # We extract the score now so the JSONL has it immediately
                                    for file_obj in violation_data:
                                        for violation in file_obj.get('violations', []):
                                            score = self._extract_metric_score(
                                                violation.get('rule', ''),
                                                violation.get('description', violation.get('message', ''))
                                            )
                                            # Inject the score directly into the violation object
                                            violation['metric_value'] = score

                                success_count += 1
                                run_status = "success"
                            except json.JSONDecodeError:
                                log_file.write(f"[WARN] Corrupt PMD output for {commit_hash}\n")
                                run_status = "corrupt_output"
                        else:
                            # [FIX] We only check pmd_success if the file is MISSING.
                            if not pmd_success:
                                # Determine failure type
                                if isinstance(pmd_out, str) and "TIMEOUT" in str(pmd_out):
                                    run_status = "timeout"
                                else:
                                    run_status = "crash"

                                # Log with truncation
                                output_str = "" if pmd_out is None else str(pmd_out)
                                if len(output_str) > 200:
                                    output_str = output_str[:200] + "... [output truncated]"
                                log_file.write(f"[FAILURE] PMD {run_status} on {commit_hash}. Output: {output_str}\n")
                            else:
                                # Success but no file (empty result / no violations)
                                run_status = "missing_output"

                    finally:
                        # Guaranteed cleanup
                        if temp_json_path.exists():
                            try:
                                temp_json_path.unlink()
                            except OSError as e:
                                log_file.write(f"[WARN] Could not delete temp file: {e}\n")

                    # [NEW FIX]: Resolve the true Commit SHA
                    # If commit_hash was an Annotated Tag, this forces Git to peel it back to the code commit.
                    resolve_cmd = ["git", "rev-parse", f"{commit_hash}^{{commit}}"]
                    res_success, true_sha = adapter_subprocess.run_command(resolve_cmd,
                                                                           cwd=str(self.target_repo_path),
                                                                           verbose=False)
                    resolved_commit_hash = true_sha.strip() if res_success and true_sha else commit_hash
                    # [FIX] Resolve actual commit timestamp (Epoch %ct) for temporal math
                    ts_cmd = ["git", "log", "-1", "--format=%ct", resolved_commit_hash]
                    ts_success, ts_output = adapter_subprocess.run_command(
                        ts_cmd, cwd=str(self.target_repo_path), verbose=False
                    )
                    commit_ts = int(ts_output.strip()) if ts_success and ts_output.strip() else int(time.time())

                    # 6. Stream to JSONL (Atomic Append)
                    record = {
                        "sha": resolved_commit_hash,  # Use the mathematically resolved SHA here!
                        "timestamp": commit_ts,
                        "status": run_status,
                        "violations": violation_data
                    }

                    try:
                        with open(self.jsonl_output_path, "a",encoding="utf-8") as jsonl_file:
                            jsonl_file.write(json.dumps(record) + "\n")
                    except Exception as e:
                        log_file.write(f"[CRITICAL] Could not write to JSONL: {e}\n")

                    # 7. Update State
                    current_time = time.time()
                    should_flush = (current_time - last_checkpoint_time >= self.checkpoint_interval_seconds) or (
                                i == len(batch) - 1)

                    self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=should_flush)

                    if should_flush:
                        last_checkpoint_time = current_time

            except KeyboardInterrupt:
                print("\n⚠️  Interrupt detected! Saving progress...")
                try:
                    self.state_manager.flush()
                except Exception as e:
                    log_file.write(f"[CRITICAL] Flush failed on interrupt: {e}\n")
                return False

            finally:
                ui_strategy.clear_line()
                print(f"   🔙 Restoring workspace state...")
                adapter_subprocess.run_command(
                    ["git", "checkout", "-f", start_state],
                    cwd=str(self.target_repo_path),
                    verbose=False
                )
                self.state_manager.flush()

        # [OUT-DENTED 4 SPACES]: Now outside the 'with open()' block
        # --- UX: Detailed Batch Summary ---
        total_processed_so_far = batch_start_index + len(batch)
        remaining = max(0, total_commits - total_processed_so_far)
        print(f"✅ Batch Complete. Scanned {total_processed_so_far}/{total_commits} | Remaining: {remaining}")

        # Only print the new metrics line if we actually did work
        if success_count > 0:
            print(f"   📈 Extracted new metrics for {success_count} commits.")

        return True