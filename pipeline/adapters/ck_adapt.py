import csv
import json
import time
import tempfile
from pathlib import Path
from typing import List, Dict

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.state.output_state import OutputDerivedState
from pipeline.adapters.i_adapters import IAdapter


class CkAdapter(IAdapter):
    """
    Stateful Adapter for Maurício Aniche's CK Tool.
    Strategy: 'Time-Travel Batching' with JSONL Streaming (Scalable).
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.checkpoint_interval_seconds = 300
        # Sampling State: Stores the set of interesting SHAs
        self.sampling_filter = None

        # Output to a single JSONL file instead of a directory
        self.jsonl_output_path = config.OUTPUTS_PATH / f"ck_metrics_{self.target_repo_path.name}.jsonl"

        # Progress is read back from the output, so this must follow the path it reads.
        # set_sampling_filter() reroutes the output and rebuilds this against the new file.
        self.state = OutputDerivedState(self.jsonl_output_path, "sha", label="ck")

    def set_sampling_filter(self, sampled_shas: set):
        """[OVERRIDE] Configure the adapter to skip uninteresting commits and isolate data."""
        self.sampling_filter = sampled_shas

        # [FIX] Isolate the data streams so full-runs and sampled-runs don't contaminate each other
        sampled_prefix = "ck_sampled"

        # 1. Reroute the JSONL data stream
        self.jsonl_output_path = config.OUTPUTS_PATH / f"{sampled_prefix}_metrics_{self.target_repo_path.name}.jsonl"

        # 2. Re-initialize a brand new State Manager pointing to a different memory file
        # A sampled run writes to a different file, so progress is re-read from that one.
        self.state = OutputDerivedState(self.jsonl_output_path, "sha", label=sampled_prefix)

        print(f"   🎯 Adapter Strategy Update: Filtering for {len(self.sampling_filter)} specific commits.")
        print(f"   📂 Redirecting data stream to: {self.jsonl_output_path.name}")

    def get_tool_name(self) -> str:
        mode = "Sampled " if self.sampling_filter else ""
        return f"CK Metrics ({mode}Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        mode = "sampled_" if self.sampling_filter else ""
        return config.OUTPUTS_PATH / f"ck_execution_{mode}{self.target_repo_path.name}.log"

    def _get_ordered_targets(self) -> List[str]:
        """Every snapshot this run should cover, in chronological order."""

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

        if self.sampling_filter:
            return [sha for sha in all_commits_ordered if sha in self.sampling_filter]
        return all_commits_ordered

    def _get_commit_batch(self) -> List[str]:
        """
        The next snapshots to process, selected BY SHA rather than by index.

        An index assumes the ordered list is identical to the one the previous run saw.
        Re-mining the release grid or changing the sample changes that list, and every position
        after the change then maps onto the wrong snapshot -- silently, since a shifted index is
        still a valid index. A SHA is intrinsic to the commit, so a list that grows or reorders
        is absorbed with nothing to reconcile.
        """
        return self.state.unprocessed(self._get_ordered_targets())[:self.batch_size]

    def _get_total_commit_count(self) -> int:
        cmd = ["git", "rev-list", "--count", "HEAD"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(self.target_repo_path), verbose=False)
        return int(output.strip()) if success and output and output.strip() else 0

    def _parse_csv_to_dicts(self, csv_path: Path) -> List[Dict]:
        """Internal Utility: Reads a CSV file and returns a list of dictionaries."""
        if not csv_path.exists():
            return []

        data = []
        # [FIX] Do not swallow exceptions. Let them bubble up so run_status="crash"
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data

    def _normalize_ck_path(self, abs_path_str: str) -> str:
        """[REVIEW FIX]: Normalizes CK absolute paths to pure relative paths."""
        try:
            # Safely resolve the path CK gave us
            p = Path(abs_path_str).resolve()
            # Strip out the absolute workspace path, leaving ONLY the repo-relative path
            rel_path = p.relative_to(self.target_repo_path.resolve())
            # Return pure relative path (e.g., src/main/java/...) with forward slashes
            return str(rel_path).replace('\\', '/')
        except ValueError:
            return abs_path_str  # Fallback if path manipulation fails

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

        # Position within the whole target list, for progress only -- never for selection.
        idx_map = {sha: n for n, sha in enumerate(self._get_ordered_targets())}

        with open(log_path, "a", encoding="utf-8") as log_file:
            try:
                for i, commit_hash in enumerate(batch):
                    # True position, not an offset: batches may be non-contiguous where earlier
                    # snapshots are already recorded.
                    global_index = idx_map.get(commit_hash, i)

                    ui_strategy.update_progress(
                        global_index + 1,
                        total_commits,
                        prefix=f"   🔄 Processing [{commit_hash[:7]}]"
                    )

                    # 2. Check if already processed (Idempotency)
                    if self.state.is_processed(commit_hash):
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
                                "timestamp": 0,
                                "status": "checkout_failed",
                                "metrics": []
                            }
                            with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                                jsonl_file.write(json.dumps(status_record) + "\n")
                        except Exception as e:
                            log_file.write(f"[WARN] Failed to write checkout_failed record to JSONL: {e}\n")

                        self.state.mark_processed(commit_hash)
                        continue

                    # 4. Run CK (Isolated Temp Directory)
                    merged_classes = []
                    run_status = "pending"

                    with tempfile.TemporaryDirectory() as temp_dir:

                        # [FIX 1]: CK Path Concatenation Bug
                        # We must force a trailing slash so CK doesn't write outside the temp folder.
                        ck_out_dir = str(temp_dir).replace('\\', '/')
                        if not ck_out_dir.endswith('/'):
                            ck_out_dir += '/'

                        # [FIX 2]: Normalize repo path for Eclipse JDT on Windows
                        repo_dir_str = str(self.target_repo_path).replace('\\', '/')

                        # CK CLI Arguments: <project_dir> <use_jars> <max_at_once> <variables_and_fields> <output_dir>
                        # Use lowercase 'false'/'true' to perfectly match Java Boolean parsing
                        ck_cmd = [
                            "java", "-jar", str(config.CK_PATH),
                            repo_dir_str,
                            "false", "0", "true", ck_out_dir
                        ]

                        try:
                            ck_success, ck_out = adapter_subprocess.run_command(
                                ck_cmd,
                                cwd=str(self.target_repo_path),
                                allowed_exit_codes=[0],
                                verbose=False,
                                timeout=600
                            )
                            # log_file.write(
                            #     f"[DEBUG] CK exit={ck_success} sha={commit_hash[:7]} output={str(ck_out)[:500]}\n")
                            # log_file.write(f"[DEBUG] Temp dir files: {list(Path(temp_dir).glob('*'))}\n")
                            # log_file.write(f"[DEBUG] Repo csv files: {list(self.target_repo_path.glob('*.csv'))}\n")
                            # log_file.write(f"[WARN] CK reported success but produced no CSV for {commit_hash}\n")

                            # 5. Capture Data
                            temp_dir_path = Path(temp_dir)

                            # Preferred location (what we asked CK to use)
                            class_csv = temp_dir_path / "class.csv"
                            method_csv = temp_dir_path / "method.csv"

                            # Fallback: CK sometimes writes in CWD (repo dir) even when it prints "Metrics extracted!!!"
                            if not class_csv.exists() or class_csv.stat().st_size == 0:
                                class_csv = self.target_repo_path / "class.csv"
                                method_csv = self.target_repo_path / "method.csv"

                            if class_csv.exists() and class_csv.stat().st_size > 0:
                                classes_data = self._parse_csv_to_dicts(class_csv)
                                methods_data = self._parse_csv_to_dicts(method_csv)

                                # [REVIEW FIX]: Apply path normalization via class method
                                for cls in classes_data:
                                    if "file" in cls:
                                        cls["file"] = self._normalize_ck_path(cls["file"])

                                for method in methods_data:
                                    if "file" in method:
                                        method["file"] = self._normalize_ck_path(method["file"])

                                # [REVIEW FIX]: Explicitly clean up fallback CSVs if CK wrote them to the repo root
                                if class_csv.parent.resolve() == self.target_repo_path.resolve():
                                    class_csv.unlink(missing_ok=True)
                                    method_csv.unlink(missing_ok=True)

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
                                if ck_success:
                                    run_status = "missing_output"
                                    # [DIAGNOSTIC BLOCK]: Why did CK succeed but produce no output?
                                    try:
                                        # Recursively count Java files in the repo at this commit
                                        java_files = list(self.target_repo_path.rglob('*.java'))

                                        log_file.write(
                                            f"[DEBUG] CK exit={ck_success} sha={commit_hash[:7]} output={str(ck_out)[:500]}\n")
                                        log_file.write(f"[DEBUG] Temp dir files: {list(temp_dir_path.glob('*'))}\n")
                                        log_file.write(
                                            f"[DEBUG] Repo csv files: {list(self.target_repo_path.glob('*.csv'))}\n")

                                        if not java_files:
                                            log_file.write(
                                                f"[WARN] CK produced no CSV for {commit_hash}. Reason: 0 '.java' files exist in this commit.\n")
                                        else:
                                            log_file.write(
                                                f"[WARN] CK produced no CSV for {commit_hash}. Anomaly: Found {len(java_files)} '.java' files, but CK did not parse them.\n")
                                    except Exception as e:
                                        log_file.write(
                                            f"[WARN] Failed to evaluate missing CSV reason for {commit_hash}: {e}\n")
                                else:
                                    # CK actually crashed or timed out
                                    if isinstance(ck_out, str) and "TIMEOUT" in str(ck_out):
                                        run_status = "timeout"
                                    else:
                                        run_status = "crash"

                                    output_str = "" if ck_out is None else str(ck_out)
                                    if len(output_str) > 200:
                                        output_str = output_str[:200] + "... [output truncated]"
                                    log_file.write(
                                        f"[FAILURE] CK {run_status} on {commit_hash}. Output: {output_str}\n")

                        except Exception as e:
                            log_file.write(f"[CRITICAL] Unexpected error during CK run: {e}\n")
                            run_status = "crash"

                    # Resolve the true Commit SHA
                    resolve_cmd = ["git", "rev-parse", f"{commit_hash}^{{commit}}"]
                    res_success, true_sha = adapter_subprocess.run_command(
                        resolve_cmd, cwd=str(self.target_repo_path), verbose=False
                    )
                    resolved_commit_hash = true_sha.strip() if res_success and true_sha else commit_hash

                    # [FIX] Resolve actual commit timestamp (Epoch %ct) for temporal math
                    ts_cmd = ["git", "log", "-1", "--format=%ct", resolved_commit_hash]
                    ts_success, ts_output = adapter_subprocess.run_command(
                        ts_cmd, cwd=str(self.target_repo_path), verbose=False
                    )
                    commit_ts = int(ts_output.strip()) if ts_success and ts_output.strip() else int(time.time())

                    # 6. Stream to JSONL (Atomic Append)
                    record = {
                        "sha": resolved_commit_hash,
                        "timestamp": commit_ts, # [FIX] Using actual Git timestamp
                        "status": run_status,
                        "metrics": merged_classes
                    }

                    try:
                        with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                            jsonl_file.write(json.dumps(record) + "\n")
                    except Exception as e:
                        log_file.write(f"[CRITICAL] Could not write to JSONL: {e}\n")

                    # 7. Update State
                    # The JSONL record above is what makes this durable; this only stops the
                    # same run from processing the snapshot twice.
                    self.state.mark_processed(commit_hash)

            except KeyboardInterrupt:
                # Nothing to save: every snapshot already written to the JSONL is already
                # recorded progress.
                print("\n⚠️  Interrupt detected. Records already written are kept.")
                return False

            finally:
                ui_strategy.clear_line()
                print(f"   🔙 Restoring workspace state...")
                adapter_subprocess.run_command(
                    ["git", "checkout", "-f", start_state],
                    cwd=str(self.target_repo_path),
                    verbose=False
                )

        # [OUT-DENTED 4 SPACES]: Now outside the 'with open()' block
        # --- UX: Detailed Batch Summary ---
        total_processed_so_far = len(self.state)
        remaining = max(0, total_commits - total_processed_so_far)
        print(f"✅ Batch Complete. Scanned {total_processed_so_far}/{total_commits} | Remaining: {remaining}")

        # Only print the new metrics line if we actually did work
        if success_count > 0:
            print(f"   📈 Extracted new metrics for {success_count} commits.")

        return True