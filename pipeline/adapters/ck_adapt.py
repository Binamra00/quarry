import csv
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.state.output_state import OutputDerivedState
from pipeline.adapters.i_adapters import IAdapter


# Statuses that mean the snapshot HAS BEEN MEASURED and never needs mining again.
#
#   success        classes and methods parsed
#   empty_methods  classes parsed, no methods -- CK ran and answered
#   empty_output   CK exited 0 and wrote a parseable file containing nothing
#
# empty_output is terminal ON PURPOSE, and it is the debatable one. A snapshot with no
# compilable Java genuinely has no metrics, so re-mining it every run would never converge.
# But an empty file is also what a systematic CK parse failure looks like, so while such a
# cause is under investigation, pass terminal_statuses without it and those snapshots come
# back on the next run.
CK_TERMINAL_STATUSES = frozenset({"success", "empty_methods", "empty_output"})

# Everything else -- crash, timeout, missing_output, checkout_failed -- is a statement about
# the RUN, not about the snapshot. Those records exist so the failure is visible; they must
# not be mistaken for a completed measurement.


def _ck_record_is_done(record: Dict, terminal: frozenset) -> bool:
    """
    Whether a JSONL record represents a snapshot that is finished with.

    A record written before the status field existed carries no verdict; it came from a build
    that only wrote on success, so it is treated as complete. Anything else is judged by its
    status.
    """
    status = record.get("status")
    if status is None:
        return True
    return status in terminal


class CkAdapter(IAdapter):
    """
    Stateful Adapter for Maurício Aniche's CK Tool.
    Strategy: 'Time-Travel Batching' with JSONL Streaming (Scalable).

    FAILURES ARE RECORDED, AND RECORDING THEM IS NOT THE SAME AS COMPLETING THEM
        Every snapshot produces a JSONL line, including the ones where CK crashed, timed out,
        wrote nothing, or could not even be checked out. That is what makes a partial grid
        visible instead of silently short.

        It also means the output alone can no longer answer "what is left to do", because a
        crash record and a success record look equally present. The done-predicate below is
        what separates them: a snapshot recorded as crashed is handed back to the next run, and
        appends a second record for the same SHA. The LAST record for a SHA is the current one,
        which is the rule OutputDerivedState reads by and downstream consumers must follow.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50,
                 terminal_statuses: frozenset = CK_TERMINAL_STATUSES):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.terminal_statuses = terminal_statuses
        # Sampling State: Stores the set of interesting SHAs
        self.sampling_filter = None

        # `git rev-list` over a large repo is not free and the answer cannot change mid-run.
        self._ordered_targets: Optional[List[str]] = None

        # Output to a single JSONL file instead of a directory
        self.jsonl_output_path = config.OUTPUTS_PATH / f"ck_metrics_{self.target_repo_path.name}.jsonl"

        # Progress is read back from the output, so this must follow the path it reads.
        # set_sampling_filter() reroutes the output and rebuilds this against the new file.
        self.state = OutputDerivedState(self.jsonl_output_path, "sha", label="ck",
                                        is_done=self._is_done)

    def _is_done(self, record: Dict) -> bool:
        return _ck_record_is_done(record, self.terminal_statuses)

    def set_sampling_filter(self, sampled_shas: set):
        """[OVERRIDE] Configure the adapter to skip uninteresting commits and isolate data."""
        self.sampling_filter = sampled_shas

        # [FIX] Isolate the data streams so full-runs and sampled-runs don't contaminate each other
        sampled_prefix = "ck_sampled"

        # 1. Reroute the JSONL data stream
        self.jsonl_output_path = config.OUTPUTS_PATH / f"{sampled_prefix}_metrics_{self.target_repo_path.name}.jsonl"

        # 2. Re-initialize a brand new State Manager pointing to a different memory file
        # A sampled run writes to a different file, so progress is re-read from that one.
        self.state = OutputDerivedState(self.jsonl_output_path, "sha", label=sampled_prefix,
                                        is_done=self._is_done)

        # 3. The target list is now a different list (and a different rev-list invocation),
        #    so anything cached from before the filter was applied is wrong.
        self._ordered_targets = None

        print(f"   🎯 Adapter Strategy Update: Filtering for {len(self.sampling_filter)} specific commits.")
        print(f"   📂 Redirecting data stream to: {self.jsonl_output_path.name}")

    def get_tool_name(self) -> str:
        mode = "Sampled " if self.sampling_filter else ""
        return f"CK Metrics ({mode}Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        mode = "sampled_" if self.sampling_filter else ""
        return config.OUTPUTS_PATH / f"ck_execution_{mode}{self.target_repo_path.name}.log"

    def _get_ordered_targets(self) -> List[str]:
        """
        Every snapshot this run should cover, in chronological order.

        Cached: this is called for batch selection AND to build the progress index, and on
        dubbo or questdb each call is a full `git rev-list` over six figures of history. The
        answer cannot change while a run is in flight; set_sampling_filter() clears the cache
        because it does change the question.
        """
        if self._ordered_targets is not None:
            return self._ordered_targets

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
            # Not cached: an empty result here is a failed git call, not an empty repository,
            # and caching it would make one transient failure permanent for the whole run.
            return []

        all_commits_ordered = output.strip().split('\n')

        if self.sampling_filter:
            targets = [sha for sha in all_commits_ordered if sha in self.sampling_filter]
            missing = self.sampling_filter - set(targets)
            if missing:
                raise RuntimeError(
                    f"❌ {len(missing)} sampled SHAs absent from `git rev-list --all` "
                    f"in {self.target_repo_path.name} (e.g. {sorted(missing)[:3]}). "
                    f"Refusing to mine a partial release grid."
                )
            self._ordered_targets = targets
            return targets

        self._ordered_targets = all_commits_ordered
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

    def _locate_csv(self, name: str, temp_dir_path: Path) -> Tuple[Optional[Path], str]:
        """
        Where CK actually wrote `name`, and which location that was.

        CK is asked to write into a temp directory and usually does, but sometimes writes into
        the CWD -- the repository root -- while still reporting success. Both are checked.

        The two files are located INDEPENDENTLY. Resolving them together, as this did
        originally, means an intact class.csv in the temp directory pins method.csv there as
        well, so a method.csv written to the repo root is never found and the snapshot is
        recorded as having no methods at all.

        Returns (path, source) where source is 'temp', 'repo_root' or 'absent'. A file that
        exists but is zero bytes counts as absent: CK opened it and wrote nothing, which is not
        a parseable result. A HEADER-ONLY file is a different thing -- CK wrote a schema and no
        rows -- and is returned, so the caller can tell the two apart.
        """
        preferred = temp_dir_path / name
        if preferred.exists() and preferred.stat().st_size > 0:
            return preferred, "temp"

        fallback = self.target_repo_path / name
        if fallback.exists() and fallback.stat().st_size > 0:
            return fallback, "repo_root"

        return None, "absent"

    def _cleanup_stray_csvs(self) -> None:
        """
        Remove CK output left in the repository root.

        `git clean -fdx` at the top of the next iteration would remove these, which covers every
        snapshot except the last one in a batch -- and after that one the workspace is handed
        back to the next miner with two untracked CSVs in it.
        """
        for name in ("class.csv", "method.csv", "field.csv", "variable.csv"):
            try:
                (self.target_repo_path / name).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _java_available() -> bool:
        """
        Whether a JRE can be invoked at all.

        Worth one subprocess before the loop. Without it a missing or broken java produces a
        `crash` record for every snapshot in the grid -- 542 of them, each one indistinguishable
        from a genuine CK failure until someone reads the log.
        """
        ok, _ = adapter_subprocess.run_command(
            ["java", "-version"], verbose=False, timeout=60)
        return ok

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")

        if not config.CK_PATH.exists():
            print(f"❌ Error: CK tool not found at {config.CK_PATH}. Please run provisioner.")
            return False

        if not self._java_available():
            print("❌ Error: `java -version` failed. CK is a JAR and cannot run without a JRE.")
            print("   Refusing to start: without java every snapshot would be recorded as a")
            print("   crash, burying a configuration problem in 500 identical failures.")
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
        success_count = 0

        # Every snapshot lands in exactly one bucket. Printed at the end, because a run that
        # only reports its successes cannot tell you it produced a partial grid.
        status_tally = Counter()

        # Position within the whole target list, for progress only -- never for selection.
        idx_map = {sha: n for n, sha in enumerate(self._get_ordered_targets())}

        with open(log_path, "a", encoding="utf-8") as log_file:
            # The log is opened in append mode across runs, so without a header the entries of
            # three sessions read as one undelimited stream.
            log_file.write(
                f"\n=== RUN {datetime.now().isoformat(timespec='seconds')} "
                f"repo={self.target_repo_path.name} batch={len(batch)}/{total_commits} "
                f"sampled={bool(self.sampling_filter)} ===\n")
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

                    # 2. Check if already handled (Idempotency)
                    # is_attempted, not is_processed: a snapshot that failed a moment ago is
                    # deliberately NOT processed, and must still not be entered twice in one run.
                    if self.state.is_attempted(commit_hash):
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

                        # Emit a JSONL record for this failed checkout to keep data consistent.
                        #
                        # timestamp is null, not 0. The commit could not be checked out, so its
                        # date is unknown -- and 0 is a real epoch that reads as 1970-01-01,
                        # which would sort ahead of every genuine snapshot in any temporal join.
                        try:
                            status_record = {
                                "sha": commit_hash,
                                "timestamp": None,
                                "status": "checkout_failed",
                                "n_classes": 0,
                                "n_methods": 0,
                                "csv_source": None,
                                "metrics": []
                            }
                            with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                                jsonl_file.write(json.dumps(status_record) + "\n")
                        except Exception as e:
                            log_file.write(f"[WARN] Failed to write checkout_failed record to JSONL: {e}\n")

                        status_tally["checkout_failed"] += 1
                        # done=False: a checkout failure says nothing about the snapshot's
                        # metrics, so it must not close the snapshot out.
                        self.state.mark_processed(commit_hash, done=False)
                        continue

                    # 4. Run CK (Isolated Temp Directory)
                    merged_classes = []
                    run_status = "pending"
                    classes_data, methods_data = [], []
                    csv_source = None

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

                            # Located independently: an intact class.csv in the temp directory
                            # must not pin method.csv there too. See _locate_csv.
                            class_csv, class_src = self._locate_csv("class.csv", temp_dir_path)
                            method_csv, method_src = self._locate_csv("method.csv", temp_dir_path)
                            csv_source = class_src

                            # Recorded BEFORE anything is deleted, because the diagnostics below
                            # need to know where CK actually wrote -- and the cleanup that runs
                            # a few lines later removes exactly that evidence.
                            temp_listing = sorted(p.name for p in temp_dir_path.glob("*"))
                            root_listing = sorted(p.name for p in
                                                  self.target_repo_path.glob("*.csv"))

                            if class_csv is not None:
                                classes_data = self._parse_csv_to_dicts(class_csv)
                                methods_data = (self._parse_csv_to_dicts(method_csv)
                                                if method_csv is not None else [])

                                # [REVIEW FIX]: Apply path normalization via class method
                                for cls in classes_data:
                                    if "file" in cls:
                                        cls["file"] = self._normalize_ck_path(cls["file"])

                                for method in methods_data:
                                    if "file" in method:
                                        method["file"] = self._normalize_ck_path(method["file"])

                                # [REVIEW FIX]: Explicitly clean up CK output written to the repo
                                # root. Unconditional now: the two files are located separately,
                                # so either one of them may be the stray.
                                self._cleanup_stray_csvs()

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

                                if not merged_classes:
                                    # class.csv existed but carried only a header: CK ran, wrote
                                    # a file and parsed nothing. Indistinguishable from a snapshot
                                    # that genuinely has no classes unless it is recorded here -
                                    # checkstyle 7.5+ produced 143 such snapshots, every one
                                    # written as "success" with an empty log.
                                    run_status = "empty_output"
                                    self._diagnose_empty(
                                        log_file, commit_hash, ck_out,
                                        classes_data, methods_data,
                                        class_src, method_src, temp_listing, root_listing)

                                elif not methods_data:
                                    # Classes parsed, methods did not. Every class then gets an
                                    # empty `methods` list and the snapshot looks structurally
                                    # complete while carrying no method-level metrics at all --
                                    # which is the level RQ2 and RQ4 rank at.
                                    #
                                    # The snapshot IS measured, so this is terminal rather than
                                    # retryable, but it is not "success" and must not be counted
                                    # as one.
                                    run_status = "empty_methods"
                                    success_count += 1
                                    self._diagnose_empty(
                                        log_file, commit_hash, ck_out,
                                        classes_data, methods_data,
                                        class_src, method_src, temp_listing, root_listing)

                                else:
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
                                            f"[DEBUG] CK exit={ck_success} sha={commit_hash[:7]} "
                                            f"output_tail={self._tail(ck_out)}\n")
                                        log_file.write(f"[DEBUG] Temp dir files: {temp_listing}\n")
                                        log_file.write(f"[DEBUG] Repo csv files: {root_listing}\n")

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
                                    # CK actually crashed or timed out.
                                    #
                                    # Equality, not substring: run_command returns the literal
                                    # string "TIMEOUT" and nothing else on a timeout, whereas
                                    # ck_out on a crash is CK's own stdout+stderr and can contain
                                    # any word at all.
                                    run_status = "timeout" if ck_out == "TIMEOUT" else "crash"

                                    log_file.write(
                                        f"[FAILURE] CK {run_status} on {commit_hash}. "
                                        f"Output tail: {self._tail(ck_out)}\n")

                        except Exception as e:
                            # The merge loop may already have appended to merged_classes before
                            # the exception fired. A record marked "crash" must not also carry
                            # half a snapshot's metrics -- a downstream reader filtering on
                            # status would drop it, but one filtering on `metrics` being
                            # non-empty would silently accept a truncated class list.
                            merged_classes = []
                            classes_data, methods_data = [], []
                            log_file.write(
                                f"[CRITICAL] Unexpected error during CK run for {commit_hash}: "
                                f"{type(e).__name__}: {e}\n")
                            run_status = "crash"

                    # A status is assigned on every path above, so "pending" reaching this point
                    # means a branch was added without one. Recorded as a crash rather than
                    # written out, because an unrecognised status would be read as terminal by
                    # nothing and as retryable by nothing.
                    if run_status == "pending":
                        log_file.write(
                            f"[CRITICAL] {commit_hash} left CK with no status assigned. "
                            f"Recording as crash.\n")
                        run_status = "crash"
                        merged_classes = []

                    # Resolve the true Commit SHA.
                    #
                    # `git rev-list` emits commit SHAs, so this is normally a no-op and the
                    # resolved hash equals commit_hash -- which is what lets the JSONL (keyed on
                    # the resolved hash) be compared against the target list (the raw hashes) on
                    # the next run. If a target list is ever fed tag OBJECT shas, the two diverge
                    # and every snapshot is re-mined forever.
                    resolve_cmd = ["git", "rev-parse", f"{commit_hash}^{{commit}}"]
                    res_success, true_sha = adapter_subprocess.run_command(
                        resolve_cmd, cwd=str(self.target_repo_path), verbose=False
                    )
                    resolved_commit_hash = true_sha.strip() if res_success and true_sha else commit_hash

                    # [FIX] Resolve actual commit timestamp (Epoch %ct) for temporal math.
                    #
                    # null on failure, NOT time.time(). Stamping a 2015 snapshot with today's
                    # epoch produces a plausible number that silently reorders the release grid;
                    # a null is loud at the point of use and can be filtered.
                    ts_cmd = ["git", "log", "-1", "--format=%ct", resolved_commit_hash]
                    ts_success, ts_output = adapter_subprocess.run_command(
                        ts_cmd, cwd=str(self.target_repo_path), verbose=False
                    )
                    if ts_success and ts_output and ts_output.strip().isdigit():
                        commit_ts = int(ts_output.strip())
                    else:
                        commit_ts = None
                        log_file.write(
                            f"[WARN] Could not resolve commit timestamp for "
                            f"{resolved_commit_hash}; recorded as null.\n")

                    # 6. Stream to JSONL (Atomic Append)
                    #
                    # n_classes / n_methods are stored alongside the metrics so the integrity
                    # check is a scan of scalars rather than a parse of every nested class list.
                    record = {
                        "sha": resolved_commit_hash,
                        "timestamp": commit_ts,   # [FIX] Actual Git timestamp, or null
                        "status": run_status,
                        "n_classes": len(classes_data),
                        "n_methods": len(methods_data),
                        "csv_source": csv_source,  # 'temp' | 'repo_root' | 'absent' | None
                        "metrics": merged_classes
                    }

                    written = True
                    try:
                        with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                            jsonl_file.write(json.dumps(record) + "\n")
                    except Exception as e:
                        written = False
                        log_file.write(f"[CRITICAL] Could not write to JSONL: {e}\n")

                    status_tally[run_status] += 1

                    # 7. Update State
                    # The JSONL record above is what makes this durable; this only stops the
                    # same run from processing the snapshot twice.
                    #
                    # done is false for a failure status AND for a record that never reached
                    # disk: in both cases the snapshot still owes a measurement, and the next
                    # run must pick it up.
                    self.state.mark_processed(
                        commit_hash,
                        done=written and run_status in self.terminal_statuses)

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
                # Checkout restores TRACKED files only. CK output written to the repo root is
                # untracked and would otherwise be handed to the next miner as a dirty tree.
                self._cleanup_stray_csvs()
                adapter_subprocess.run_command(
                    ["git", "clean", "-fdx"],
                    cwd=str(self.target_repo_path),
                    verbose=False
                )
                log_file.write(
                    f"--- END {datetime.now().isoformat(timespec='seconds')} "
                    f"{dict(sorted(status_tally.items()))} ---\n")

        # [OUT-DENTED 4 SPACES]: Now outside the 'with open()' block
        # --- UX: Detailed Batch Summary ---
        total_processed_so_far = len(self.state)
        remaining = max(0, total_commits - total_processed_so_far)
        print(f"✅ Batch Complete. Scanned {total_processed_so_far}/{total_commits} | Remaining: {remaining}")

        # Only print the new metrics line if we actually did work
        if success_count > 0:
            print(f"   📈 Extracted new metrics for {success_count} commits.")

        # Every snapshot in one line. A run that reports only its successes cannot tell you it
        # produced a partial grid -- which is the whole reason the statuses are recorded.
        if status_tally:
            print("   📋 " + " | ".join(f"{k}={v}" for k, v in sorted(status_tally.items())))

        retry_count = sum(v for k, v in status_tally.items()
                          if k not in self.terminal_statuses)
        if retry_count:
            print(f"   ♻️  {retry_count} snapshot(s) did not complete and will be re-attempted "
                  f"on the next run.")
            print(f"      Diagnostics: {log_path.name}")

        return True

    # ------------------------------------------------------------------ diagnostics

    @staticmethod
    def _tail(output, n: int = 500) -> str:
        """
        The END of a CK invocation's output.

        CK prints a line per source file, so the first n characters of a large run are the first
        few files it touched and say nothing. The outcome -- "Metrics extracted!!!", or the JDT
        stack trace that replaced it -- is at the tail.
        """
        if output is None:
            return ""
        text = str(output).strip()
        return text if len(text) <= n else "... [truncated] " + text[-n:]

    def _diagnose_empty(self, log_file, commit_hash, ck_out,
                        classes_data, methods_data,
                        class_src, method_src, temp_listing, root_listing) -> None:
        """
        Why did CK exit 0 and produce a file with nothing useful in it?

        Two causes look identical in the output and are opposite in meaning:

            the snapshot really has no compilable Java  -> a valid measurement
            CK wrote its real output somewhere else     -> a mining failure

        `class_src` and `method_src` separate them: the first says the file was read from where
        CK was told to write, the second says it was scavenged from the repository root, and
        'absent' says neither existed. The directory listings are captured before cleanup so
        they still show what CK left behind.
        """
        try:
            java_files = list(self.target_repo_path.rglob("*.java"))
            log_file.write(
                f"[WARN] CK parsed no {'classes' if not classes_data else 'methods'} for "
                f"{commit_hash}: class rows={len(classes_data)}, "
                f"method rows={len(methods_data)}, "
                f"class.csv from={class_src}, method.csv from={method_src}, "
                f"'.java' files in checkout={len(java_files)}, "
                f"temp dir={temp_listing}, repo root csv={root_listing}. "
                f"CK output tail: {self._tail(ck_out, 300)}\n")
        except Exception as e:
            log_file.write(
                f"[WARN] Failed to diagnose empty CK output for {commit_hash}: {e}\n")