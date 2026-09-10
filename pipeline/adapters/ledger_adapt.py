import json
import time
from pathlib import Path
from typing import Dict, List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.state.output_state import OutputDerivedState
from pipeline.scope import CommitUniverse
from pipeline.adapters.i_adapters import IAdapter

try:
    from pydriller import Repository
except ImportError:
    Repository = None


class LedgerAdapter(IAdapter):
    """
    Stateful Adapter for Evolutionary Ledger Mining (using PyDriller).
    Strategy: 'Graph Traversal Batching' with JSONL Streaming.

    SCOPE: behaviour only. For each commit this records WHO changed WHAT, WHEN, and HOW MUCH --
    author, timestamp, files touched, line churn, methods changed. Keyed by SHA, it is the
    file-level lookup that every trigger channel resolves through:

        channel record -> ref -> commit SHA -> ledger -> files, churn, methods

    It holds NO trigger logic. A former `is_bug_fix` field applied a keyword regex to the commit
    message and was removed: recognising a trigger is the detector's job, and the commit message
    is text belonging to the commit CHANNEL, which mines it in its own pass. Mixing detection
    into the ledger coupled two concerns and hard-coded a single trigger into a component that
    must stay trigger-agnostic.

    Note: JSONL mined before this change carries a vestigial `is_bug_fix` key. Nothing reads it,
    so no re-mining is required; it disappears on any future re-mine.
    """

    def __init__(self, target_repo_path: Path, batch_size: int = 50, universe_path: str = None):
        super().__init__(target_repo_path)
        self.batch_size = batch_size
        self.checkpoint_interval_seconds = 300

        # Commit universe. If universe_path is None the adapter is "dumb": it mines --all
        # (the whole repository, matching the metadata source of truth). If a universe file is
        # given, it mines exactly the pinned study grid. Shared with RefactoringMiner so an
        # explicit run cannot have the two miners walk different sets.
        self.universe = CommitUniverse(target_repo_path.name, universe_path=universe_path)
        self._all_commits = None   # lazily populated by _get_all_commits()

        self.jsonl_output_path = config.OUTPUTS_PATH / f"ledger_history_{self.target_repo_path.name}.jsonl"

        # Progress comes from the output itself, not a parallel state file. A commit appears in
        # the JSONL if and only if it was mined, so the two cannot disagree -- which removes the
        # window where a hard kill between the record write and the state flush caused a commit
        # to be mined twice.
        self.state = OutputDerivedState(self.jsonl_output_path, "sha", label="ledger")

    def get_tool_name(self) -> str:
        return f"Evolutionary Ledger (Stateful Batch: {self.batch_size})"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"ledger_execution_{self.target_repo_path.name}.log"

    def _get_all_commits(self) -> List[str]:
        """
        The full ordered commit universe, oldest first. Cached: the count, the batch, and the
        index map all derive from this one list, so they cannot disagree with each other.
        """
        if self._all_commits is None:
            cmd = ["git", "rev-list", *self.universe.rev_list_args(), "--reverse"]
            success, output = adapter_subprocess.run_command(
                cmd, cwd=str(self.target_repo_path), verbose=False)
            if not success or not output or not output.strip():
                self._all_commits = []
            else:
                self._all_commits = output.strip().split('\n')
        return self._all_commits

    def _get_commit_batch(self) -> List[str]:
        """
        Next batch of UNPROCESSED commits, selected by SHA rather than by index.

        Why not index slicing (the previous approach):
            The old batch was all_commits[next_start : next_start + batch_size], with next_start
            read from state. That silently assumes the commit list is identical to the one the
            previous run saw. It is not stable: re-mining the release grid changes the universe,
            and a near-mainline commit inserted at its date position shifts every index after it.
            Resumed state then maps progress onto the wrong commits, with no error raised.

        Selecting by SHA removes the assumption entirely -- identity is intrinsic to the commit
        instead of derived from its position. This mirrors RefactoringMinerAdapter, which filters
        against already-written SHAs. A universe that GROWS is absorbed automatically: the new
        commits simply appear in the unprocessed set. Nothing to reconcile, nothing to reset.
        """
        return self.state.unprocessed(self._get_all_commits())[:self.batch_size]

    def _sha_index_map(self) -> Dict[str, int]:
        """
        SHA -> position in the universe. Recomputed each run from the current list, so it is
        always consistent with the list actually being walked. Feeds global_index for progress
        display and the is_complete trigger; it is never used to SELECT commits.
        """
        return {sha: i for i, sha in enumerate(self._get_all_commits())}

    def _get_total_commit_count(self) -> int:
        return len(self._get_all_commits())

    def _report_universe_drift(self) -> None:
        """
        Report records that are no longer in the universe.

        Universe GROWTH needs no handling: new commits simply appear in the unprocessed set and
        get mined. SHRINKAGE is worth saying out loud -- if the grid was re-mined and snapshots
        dropped out, the JSONL keeps records for commits the universe no longer contains. They
        are stale rather than corrupt, and anything joining on the release grid ignores them,
        but carrying them silently is worse than reporting them.
        """
        stale = self.state.stale(self._get_all_commits())
        if stale:
            print(
                f"\n\u26a0\ufe0f  {len(stale)} commit(s) recorded in {self.jsonl_output_path.name} "
                f"are no longer in the universe.\n"
                f"   The grid was most likely re-mined and snapshots dropped out.\n"
                f"   Harmless if downstream joins on the release grid. To be exact, delete\n"
                f"   {self.jsonl_output_path.name} and re-run."
            )

    def execute(self) -> bool:
        print(f"--- 🕰️ Starting {self.get_tool_name()} ---")
        print(f"   🌐 {self.universe.describe()}")

        try:
            self.universe.verify_against(self.target_repo_path)
        except RuntimeError as e:
            print(e)
            return False

        if Repository is None:
            print("❌ Error: 'pydriller' is not installed. Please check your requirements.txt.")
            return False

        total_commits = self._get_total_commit_count()
        if total_commits == 0:
            print("❌ No commits found to analyze.")
            return False

        self._report_universe_drift()

        idx_map = self._sha_index_map()
        batch = self._get_commit_batch()

        if not batch:
            print(f"✅ Analysis already complete for all {total_commits} commits.")
            return True

        print(f"   📊 Batch Scope: {len(batch)} commits")

        log_path = self.get_output_path()
        last_checkpoint_time = time.time()
        success_count = 0
        traversed_count = 0

        with open(log_path, "a", encoding="utf-8") as log_file:
            try:
                # PyDriller Optimization: Pass the exact batch of SHAs.
                # PyDriller reads the internal Git Tree directly (No checkouts required!)
                #
                # include_refs=True is REQUIRED and not optional. PyDriller's Conf.build_args()
                # defaults its revision to 'HEAD'; only_commits is applied as a filter AFTERWARDS
                # and does NOT extend the walk. Without include_refs, near-mainline snapshot
                # commits are never reached and traverse_commits() silently yields fewer commits
                # than the batch -- which desynchronises global_index and writes wrong offsets
                # into the batch state. Verified: 5 of 7 yielded without it, 7 of 7 with it.
                # The universe stays bounded because only_commits filters the walk back down to
                # exactly the batch; this is not equivalent to mining --all.
                repo_miner = Repository(
                    str(self.target_repo_path),
                    only_commits=batch,
                    include_refs=True,
                )

                for i, commit in enumerate(repo_miner.traverse_commits()):
                    traversed_count += 1
                    commit_hash = commit.hash
                    # true position in the universe, not a running offset from a stored index.
                    # batches may now be non-contiguous (gaps where commits were already done),
                    # so batch_start_index + i would be wrong.
                    global_index = idx_map[commit_hash]

                    ui_strategy.update_progress(
                        global_index + 1,
                        total_commits,
                        prefix=f"   📖 Scanning [{commit_hash[:7]}]"
                    )

                    # 1. Check Idempotency
                    if self.state.is_processed(commit_hash):
                        continue

                    # 2. Extract Socio-Technical Metadata
                    # Behaviour only -- no trigger detection. The commit MESSAGE is not stored
                    # here; it is text, and the commit channel mines it separately.
                    record = {
                        "sha": commit_hash,
                        "timestamp": int(commit.committer_date.timestamp()),
                        "author_name": commit.author.name,
                        "author_email": commit.author.email, # [FIX] Added email for precise identity resolution
                        "modifications": []
                    }

                    # 3. Extract File-Level and Method-Level Churn (Java files only)
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

                            mod_record = {
                                "file": universal_path,
                                "old_file": old_universal_path,
                                "lines_added": mod.added_lines,
                                "lines_deleted": mod.deleted_lines,
                                "change_type": mod.change_type.name,
                                "changed_methods": [] # [NEW] Array for method-level tracking
                            }

                            # [NEW] Extract specific methods modified in this diff
                            try:
                                # PyDriller compares the before/after AST to find changed methods
                                for m in mod.changed_methods:
                                    mod_record["changed_methods"].append({
                                        "name": m.name,          # e.g., "calculateTotal"
                                        "long_name": m.long_name # e.g., "calculateTotal(int, float)"
                                    })
                            except Exception:
                                # PyDriller AST parsing can occasionally fail on malformed historical code.
                                # Catch silently to preserve the file-level metrics.
                                pass

                            record["modifications"].append(mod_record)

                    # 4. Stream to JSONL
                    try:
                        with open(self.jsonl_output_path, "a", encoding="utf-8") as jsonl_file:
                            jsonl_file.write(json.dumps(record) + "\n")
                        success_count += 1
                    except Exception as e:
                        log_file.write(f"[CRITICAL] Could not write ledger to JSONL: {e}\n")

                    # 5. Note it done for the rest of this run. The JSONL write above is what
                    #    makes it durable; there is no second record to keep in sync.
                    self.state.mark_processed(commit_hash)

            except KeyboardInterrupt:
                # Nothing to save: every commit already written to the JSONL is already recorded
                # progress. That is the point of deriving state from the output.
                print("\n⚠️  Interrupt detected. Records already written are kept.")
                return False

            except Exception as e:
                print(f"\n❌ [CRITICAL] PyDriller Crash: {e}")
                log_file.write(f"[CRITICAL] PyDriller Crash: {e}\n")
                return False

            finally:
                ui_strategy.clear_line()

        # Fail loudly rather than write wrong indices: global_index assumes traverse_commits()
        # yields exactly the batch, in the same order.
        if traversed_count != len(batch):
            print(
                f"\n❌ [CRITICAL] Traversal desync: PyDriller yielded {traversed_count} commits "
                f"for a batch of {len(batch)}.\n"
                f"   global_index offsets are therefore unreliable and state was not advanced.\n"
                f"   Check that include_refs=True is set and that the universe SHAs exist in this clone."
            )
            return False

        # --- UX: Detailed Batch Summary ---
        # counted from the processed set rather than an index arithmetic guess
        total_processed_so_far = len(self.state)
        remaining = max(0, total_commits - total_processed_so_far)
        print(f"✅ Batch Complete. Scanned {total_processed_so_far}/{total_commits} | Remaining: {remaining}")

        if success_count > 0:
            print(f"   📈 Extracted ledger events for {success_count} commits.")

        return True