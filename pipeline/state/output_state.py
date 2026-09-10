import json
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Set


class OutputDerivedState:
    """
    Progress reconstructed from a miner's own output, with no separate state file.

    WHY NOT A STATE FILE
        A state file is a second record of the same fact, and two records can disagree. The
        failure is specific: a miner writes a record to its JSONL, is killed before the state
        file is flushed, and on the next run re-processes work whose output is already on disk
        -- appending a duplicate. Flushing on interrupt narrows that window but cannot close it,
        because SIGKILL, an OOM kill and a power loss do not run handlers.

        Reading progress back from the output removes the second record entirely. The output IS
        the progress: a unit appears in the file if and only if it was completed, so the two
        cannot diverge. There is nothing to delete, nothing to keep in sync, and no state file
        whose absence silently restarts a finished job.

        RefactoringMiner has always worked this way. This generalises it so the ledger and CK
        get the same guarantee.

    WHEN A STATE FILE IS STILL REQUIRED
        Only when progress involves something the output cannot hold. The channel miner is the
        case: its position in a paginated remote and the moment an API quota resets exist
        nowhere in its records, so ChannelStateManager persists them. That is a real difference
        in kind, not an inconsistency.

    THE ONE ASSUMPTION
        One output line per unit of work, carrying that unit's identifier. All three miners
        satisfy it: the ledger writes a line per commit keyed `sha`, RefactoringMiner a line per
        commit keyed `sha1`, CK a line per snapshot keyed `sha` with its classes nested inside.

    A RECORD IS NOT AUTOMATICALLY A COMPLETION
        Written naively, "the unit appears in the file" and "the unit was mined" are the same
        statement. They stop being the same as soon as a miner records its FAILURES -- which CK
        now does, so that a crashed or empty snapshot is visible rather than absent. Treating
        those records as progress would make every failure permanent: the snapshot is in the
        file, so it is never attempted again, and the run that was supposed to fix the tool
        silently mines nothing.

        `is_done` is the predicate that separates the two. A record it rejects is REPLAYABLE:
        the unit is reported in `retryable` and handed back by `unprocessed()`, so the next run
        attempts it again. Omitting the predicate keeps the original behaviour, where every
        record counts.

    DUPLICATE IDS, AND WHY THE LAST ONE WINS
        A replayed unit appends a SECOND record with the same id -- the failure from the earlier
        run, then the success from this one. That is deliberate: the failure is evidence about
        the tool and is not worth rewriting the file to erase, and an append-only output has no
        rewrite path that is safe against interruption anyway.

        So this class reads the file in order and keeps the LAST record seen for each id. The
        newest attempt is the current state of that unit. Downstream readers must do the same --
        group by the id field and take the final occurrence -- and any reader that counts lines
        rather than distinct ids will over-count once a retry has happened.

    PARTIAL LINES
        A process killed mid-write can leave a truncated final line. It fails to parse, is
        skipped with a warning, and its unit is simply re-processed -- the conservative outcome.
        Downstream readers should treat the last line of an interrupted file as suspect and
        de-duplicate on the id, which costs nothing and is worth doing regardless.
    """

    def __init__(self, output_path: Path, id_field: str, label: str = "",
                 is_done: Optional[Callable[[Dict], bool]] = None):
        """
        Args:
            output_path: the miner's JSONL. Absent means nothing has been mined yet.
            id_field: the key identifying the unit of work -- 'sha', 'sha1'.
            label: name used in messages, e.g. 'ledger'.
            is_done: predicate deciding whether a parsed record represents COMPLETED work.
                None means every record does, which is the right answer for a miner that only
                writes on success. A miner that also records failures passes a predicate so its
                failures come back on the next run.
        """
        self.output_path = Path(output_path)
        self.id_field = id_field
        self.label = label or self.output_path.stem
        self.is_done = is_done
        self.corrupt_lines = 0

        self.processed: Set[str] = set()   # recorded AND complete
        self.retryable: Set[str] = set()   # recorded but rejected by is_done
        self._attempted: Set[str] = set()  # touched during THIS run, complete or not

        self._scan()

    # ------------------------------------------------------------------ loading

    def _scan(self) -> None:
        if not self.output_path.exists():
            return

        # id -> done-ness of the LAST record seen for that id. A dict rather than two sets,
        # because a retried unit appears twice and only the newer verdict is current.
        latest: Dict[str, bool] = {}
        bad_offsets = []          # (line number, byte offset where that line starts)

        try:
            with open(self.output_path, "r", encoding="utf-8") as f:
                offset = 0
                for n, raw in enumerate(f, start=1):
                    start = offset
                    offset += len(raw.encode("utf-8"))
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        bad_offsets.append((n, start))
                        continue
                    rid = rec.get(self.id_field)
                    if rid is None:
                        continue
                    latest[str(rid)] = True if self.is_done is None else bool(self.is_done(rec))
            self.corrupt_lines = len(bad_offsets)
            if bad_offsets:
                self._handle_corrupt(bad_offsets, offset)
        except OSError as e:
            # Do not silently start from zero: that would re-mine everything and append a full
            # duplicate set on top of output that is probably intact.
            raise RuntimeError(
                f"Could not read {self.output_path.name} to determine progress: {e}\n"
                f"   Refusing to continue, because treating this as 'nothing mined' would "
                f"duplicate every record already in the file."
            )

        self.processed = {rid for rid, done in latest.items() if done}
        self.retryable = {rid for rid, done in latest.items() if not done}

        if self.processed:
            print(f"   🔄 {len(self.processed)} unit(s) already recorded in "
                  f"{self.output_path.name}")
        if self.retryable:
            print(f"   ♻️  {len(self.retryable)} unit(s) recorded as INCOMPLETE and will be "
                  f"re-attempted this run.")

    def _handle_corrupt(self, bad_offsets, file_size: int) -> None:
        """
        Deal with lines that failed to parse.

        A process killed mid-write can only ever truncate the LAST line -- everything before it
        was already complete and flushed. So a corrupt final line is a known partial record, and
        the file is truncated to remove it: the unit is simply re-processed, and the output stays
        valid JSONL for every downstream reader.

        Leaving it in place would be worse than it sounds. The line survives every future run,
        each consumer has to defend against it, and anything counting lines silently over-counts
        by one.

        A corrupt line anywhere ELSE is not a partial write -- it is disk corruption or manual
        editing -- and truncating there would discard good records after it. Those are reported
        and left untouched.
        """
        last_n, last_start = bad_offsets[-1]
        is_final = last_start + self._line_length(last_start) >= file_size

        if is_final and len(bad_offsets) == 1:
            try:
                with open(self.output_path, "r+", encoding="utf-8") as f:
                    f.truncate(last_start)
                print(f"   🩹 {self.output_path.name}: removed a truncated final record "
                      f"(line {last_n}); its unit will be re-processed.")
            except OSError as e:
                print(f"   ⚠️  {self.output_path.name}: line {last_n} is truncated and could "
                      f"not be removed ({e}). Downstream readers must skip it.")
            return

        print(f"   ⚠️  {self.output_path.name}: {len(bad_offsets)} unparseable line(s) at "
              f"{[n for n, _ in bad_offsets]}.")
        print(f"      Not a partial write (a partial write can only be the last line), so they "
              f"are left in place. Their units will be re-processed.")

    def _line_length(self, start: int) -> int:
        try:
            with open(self.output_path, "rb") as f:
                f.seek(start)
                return len(f.readline())
        except OSError:
            return 0

    # ------------------------------------------------------------------ progress

    def is_processed(self, record_id) -> bool:
        """True iff the unit is recorded AND complete."""
        return str(record_id) in self.processed

    def is_attempted(self, record_id) -> bool:
        """
        True iff the unit is complete or has already been tried during THIS run.

        The distinction matters for a miner that replays failures: a snapshot that just crashed
        is not processed, but re-entering it inside the same run would loop.
        """
        rid = str(record_id)
        return rid in self.processed or rid in self._attempted

    def mark_processed(self, record_id, done: bool = True) -> None:
        """
        Note a unit as attempted for the remainder of THIS run.

        Deliberately does not persist: writing the record to the output already did that. This
        only stops the same run from processing a unit twice.

        `done=False` records an attempt that did NOT complete -- the unit stays out of
        `processed`, so the end-of-run count reports real progress rather than work done, and
        the next run picks it up again from its record.
        """
        rid = str(record_id)
        self._attempted.add(rid)
        if done:
            self.processed.add(rid)
            self.retryable.discard(rid)
        else:
            self.processed.discard(rid)
            self.retryable.add(rid)

    def unprocessed(self, all_ids: Iterable[str]) -> list:
        """
        The units still to do, in the order given.

        Excludes anything already attempted in this run, so a failure recorded a moment ago is
        not immediately handed back.
        """
        return [i for i in all_ids
                if str(i) not in self.processed and str(i) not in self._attempted]

    def stale(self, all_ids: Iterable[str]) -> Set[str]:
        """
        Recorded units that are no longer in the universe.

        Their presence means the universe shrank since they were mined -- typically the release
        grid was re-mined and snapshots dropped out. The records are stale rather than corrupt:
        anything joining on the grid ignores them. Worth reporting, not worth failing on.
        """
        universe = {str(i) for i in all_ids}
        return (self.processed | self.retryable) - universe

    def is_complete(self, total: int) -> bool:
        return total > 0 and len(self.processed) >= total

    def __len__(self) -> int:
        return len(self.processed)

    def describe(self, total: Optional[int] = None) -> str:
        if not self.processed and not self.retryable:
            return f"{self.label}: starting fresh"
        pending = f", {len(self.retryable)} to re-attempt" if self.retryable else ""
        if total:
            return f"{self.label}: {len(self.processed)}/{total} already recorded{pending}"
        return f"{self.label}: {len(self.processed)} already recorded{pending}"