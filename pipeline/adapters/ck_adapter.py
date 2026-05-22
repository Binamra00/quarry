import csv
import json
import time
import tempfile
import uuid
from pathlib import Path
from typing import List, Dict

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.utils.batch_state import BatchStateManager
from pipeline.adapters.i_adapters import IAdapter


class CkAdapter(IAdapter):
    """
    Stateful Adapter for Maurício Aniche's CK Tool.
    Strategy: 'Time-Travel Batching' with JSONL Streaming (Scalable).
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.state_manager = BatchStateManager(target_repo_path.name, "ck")
        self.checkpoint_interval_seconds = 300
        # Sampling State: Stores the set of interesting SHAs
        self.sampling_filter = None

        # Output to a single JSONL file instead of a directory
        self.jsonl_output_path = config.OUTPUTS_PATH / f"ck_metrics_{self.target_repo_path.name}.jsonl"

    def set_sampling_filter(self, sampled_shas: set):
        """[OVERRIDE] Configure the adapter to skip uninteresting commits."""
        self.sampling_filter = sampled_shas
        print(f"   🎯 Adapter Strategy Update: Filtering for {len(self.sampling_filter)} specific commits.")

    def get_tool_name(self) -> str:
        return f"CK Metrics (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"ck_execution_{self.target_repo_path.name}.log"

    def _get_commit_batch(self) -> List[str]:
        """
        Retrieves the next batch of commits to process.
        """
        if self.sampling_filter:
            # We sort to ensure chronological processing if tags follow a naming convention
            all_targets = sorted(list(self.sampling_filter))
            next_start = self.state_manager.get_next_start_index()
            return all_targets[next_start: next_start + self.batch_size]

        # 1. Get full history
        cmd = ["git", "rev-list", "HEAD", "--reverse"]
        success, output = adapter_subprocess.run_command(
            cmd,
            cwd=str(self.target_repo_path),
            verbose=False
        )

        # Robust check for empty/whitespace-only output
        if not success or not output or not output.strip():
            return []

        all_commits = output.strip().split('\n')
        total_commits = len(all_commits)

        # 2. Ask State Manager for the next slice
        next_start = self.state_manager.get_next_start_index()

        if next_start >= total_commits:
            return []

        return all_commits[next_start: next_start + self.batch_size]

    def _get_total_commit_count(self) -> int:
        cmd = ["git", "rev-list", "--count", "HEAD"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        return int(output.strip()) if success and output and output.strip() else 0

    def _parse_csv_to_dicts(self, csv_path: Path) -> List[Dict]:
        """Internal Utility: Reads a CSV file and returns a list of dictionaries."""
        if not csv_path.exists():
            return []

        data = []
        try:
            # utf-8-sig safely handles potential Byte Order Marks (BOM)
            with open(csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    data.append(row)
        except Exception:
            pass
        return data

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        if not config.CK_PATH.exists():
            print(f"❌ Error: CK tool not found at {config.CK_PATH}. Please run provisioner.")
            return False

        if self.sampling_filter:
            total_commits = len(self.sampling_filter)
        else:
            total_commits = self._get_total_commit_count()

        if total_commits == 0:
            print("❌ No commits found to analyze.")
            return False

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

        # Calculate start index ONCE before loop to prevent drift
        batch_start_index = self.state_manager.get_next_start_index()

        with open(log_path, "a", encoding="utf-8") as log_file:
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
                        log_file.write(f"[ERROR] Could not checkout {commit_hash}. Skipping run.\n")

                        # Emit a JSONL record for this failed checkout to keep data consistent
                        try:
                            status_record = {
                                "sha": commit_hash,
                                "timestamp": int(time.time()),
                                "status": "checkout_failed",
                                "metrics": []
                            }
                            with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                                jsonl_file.write(json.dumps(status_record) + "\n")
                        except Exception as e:
                            log_file.write(f"[WARN] Failed to write checkout_failed record to JSONL: {e}\n")

                        self.state_manager.save_progress(commit_hash, global_index, total_commits, flush=False)
                        continue

                    # 4. Run CK (Isolated Temp Directory)
                    merged_classes = []
                    run_status = "pending"

                    with tempfile.TemporaryDirectory() as temp_dir:
                        # CK CLI Arguments: <project_dir> <use_jars> <max_at_once> <variables_and_fields> <output_dir>
                        ck_cmd = [
                            "java", "-jar", str(config.CK_PATH),
                            str(self.target_repo_path),
                            "false", "0", "true", str(temp_dir)
                        ]

                        try:
                            ck_success, ck_out = adapter_subprocess.run_command(
                                ck_cmd,
                                allowed_exit_codes=[0],
                                verbose=False,
                                timeout=600
                            )

                            # 5. Capture Data
                            class_csv = Path(temp_dir) / "class.csv"
                            method_csv = Path(temp_dir) / "method.csv"

                            if class_csv.exists() and class_csv.stat().st_size > 0:
                                classes_data = self._parse_csv_to_dicts(class_csv)
                                methods_data = self._parse_csv_to_dicts(method_csv)

                                # Group methods by class name for fast O(1) lookup
                                methods_by_class = {}
                                for method in methods_data:
                                    class_name = method.get("class")
                                    if class_name not in methods_by_class:
                                        methods_by_class[class_name] = []
                                    methods_by_class[class_name].append(method)

                                # Nest the methods inside the class dictionary
                                for cls in classes_data:
                                    cls_name = cls.get("class")
                                    cls["methods"] = methods_by_class.get(cls_name, [])
                                    merged_classes.append(cls)

                                success_count += 1
                                run_status = "success"
                            else:
                                if not ck_success:
                                    if isinstance(ck_out, str) and "TIMEOUT" in str(ck_out):
                                        run_status = "timeout"
                                    else:
                                        run_status = "crash"

                                    output_str = "" if ck_out is None else str(ck_out)
                                    if len(output_str) > 200:
                                        output_str = output_str[:200] + "... [output truncated]"
                                    log_file.write(
                                        f"[FAILURE] CK {run_status} on {commit_hash}. Output: {output_str}\n")
                                else:
                                    run_status = "missing_output"

                        except Exception as e:
                            log_file.write(f"[CRITICAL] Unexpected error during CK run: {e}\n")
                            run_status = "crash"

                    # Resolve the true Commit SHA
                    resolve_cmd = ["git", "rev-parse", f"{commit_hash}^{{commit}}"]
                    res_success, true_sha = adapter_subprocess.run_command(resolve_cmd,
                                                                           cwd=str(self.target_repo_path),
                                                                           verbose=False)
                    resolved_commit_hash = true_sha.strip() if res_success and true_sha else commit_hash

                    # 6. Stream to JSONL (Atomic Append)
                    record = {
                        "sha": resolved_commit_hash,
                        "timestamp": int(time.time()),
                        "status": run_status,
                        "metrics": merged_classes
                    }

                    try:
                        with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
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

        print(f"✅ Batch Complete. Processed {success_count} new commits.")
        return True