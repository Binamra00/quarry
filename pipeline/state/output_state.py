import json
from pathlib import Path
from typing import Iterable, Optional, Set


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

    PARTIAL LINES
        A process killed mid-write can leave a truncated final line. It fails to parse, is
        skipped with a warning, and its unit is simply re-processed -- the conservative outcome.
        Downstream readers should treat the last line of an interrupted file as suspect and
        de-duplicate on the id, which costs nothing and is worth doing regardless.
    """

    def __init__(self, output_path: Path, id_field: str, label: str = ""):
        """
        Args:
            output_path: the miner's JSONL. Absent means nothing has been mined yet.
            id_field: the key identifying the unit of work -- 'sha', 'sha1'.
            label: name used in messages, e.g. 'ledger'.
        """
        self.output_path = Path(output_path)
        self.id_field = id_field
        self.label = label or self.output_path.stem
        self.corrupt_lines = 0
        self.processed: Set[str] = self._scan()

    # ------------------------------------------------------------------ loading

    def _scan(self) -> Set[str]:
        if not self.output_path.exists():
            return set()

        found: Set[str] = set()
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
                    if rid is not None:
                        found.add(str(rid))
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

        if found:
            print(f"   🔄 {len(found)} unit(s) already recorded in {self.output_path.name}")
        return found

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
        return str(record_id) in self.processed

    def mark_processed(self, record_id) -> None:
        """
        Note a unit as done for the remainder of THIS run.

        Deliberately does not persist: writing the record to the output already did that. This
        only stops the same run from processing a unit twice.
        """
        self.processed.add(str(record_id))

    def unprocessed(self, all_ids: Iterable[str]) -> list:
        """The units still to do, in the order given."""
        return [i for i in all_ids if str(i) not in self.processed]

    def stale(self, all_ids: Iterable[str]) -> Set[str]:
        """
        Recorded units that are no longer in the universe.

        Their presence means the universe shrank since they were mined -- typically the release
        grid was re-mined and snapshots dropped out. The records are stale rather than corrupt:
        anything joining on the grid ignores them. Worth reporting, not worth failing on.
        """
        return self.processed - {str(i) for i in all_ids}

    def is_complete(self, total: int) -> bool:
        return total > 0 and len(self.processed) >= total

    def __len__(self) -> int:
        return len(self.processed)

    def describe(self, total: Optional[int] = None) -> str:
        if not self.processed:
            return f"{self.label}: starting fresh"
        if total:
            return f"{self.label}: {len(self.processed)}/{total} already recorded"
        return f"{self.label}: {len(self.processed)} already recorded"