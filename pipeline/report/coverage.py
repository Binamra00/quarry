"""
The coverage report.

ONE JOB: say how much each stage and channel mined, and how much is outstanding.

    It verifies nothing, aggregates nothing, and computes no derived measures. Everything it
    prints is a count of something on disk. The previous version cross-checked the ledger
    against metadata, declared a PASS/CHECK verdict, and -- in a sibling module -- ranked
    refactoring hotspots and counted refactoring types. Those are analyses. They belong to
    whatever consumes the corpus, not to the thing that reports whether the corpus is finished.

    The practical consequence: this module can never be wrong about the data, because it never
    interprets it.
"""

import csv
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.report.i_reports import ArtifactCoverage, IReport
from pipeline.report.probes import probes_for

CSV_COLUMNS = ("stage", "artifact", "present", "records", "units",
               "ok", "empty", "failed", "duplicates", "statuses", "note")


class CoverageReport(IReport):
    """
    Runs every probe for a repository and renders the result twice: once to the console for
    the person watching, once to CSV for everything else.

    THE TWO RENDERINGS READ THE SAME OBJECTS. They are formatting functions over a list of
    ArtifactCoverage values, so the file and the screen cannot disagree about a run -- which
    they could when the console tree and the saved payload were built by separate code.
    """

    def __init__(self, target_repo_path: Path):
        self.target_repo_path = Path(target_repo_path)
        self.repo_name = self.target_repo_path.name

    # ------------------------------------------------------------------ IReport

    def get_tool_name(self) -> str:
        return "Coverage Report"

    def get_output_path(self) -> Path:
        # Named per repository. A single report.csv would be overwritten by whichever project
        # was reported on last, which is the opposite of what a record of coverage is for.
        return config.OUTPUTS_PATH / f"report_{self.repo_name}.csv"

    def run_report(self) -> None:
        rows = self.collect()
        self.print_report(rows)
        self.write_csv(rows)

    # ------------------------------------------------------------------ steps

    def collect(self) -> List[ArtifactCoverage]:
        """Ask every probe what it sees. Order is pipeline order, not discovery order."""
        return [probe.inspect() for probe in probes_for(self.repo_name)]

    def print_report(self, rows: List[ArtifactCoverage]) -> None:
        print(f"\nCoverage: {self.repo_name}")

        header = ("STAGE", "RECORDS", "UNITS", "OK", "EMPTY", "FAILED")
        widths = (28, 9, 8, 8, 7, 8)
        print("  " + "".join(h.ljust(w) for h, w in zip(header, widths)))
        print("  " + "-" * sum(widths))

        for r in rows:
            cells = (
                r.stage[:27],
                self._num(r.records) if r.present else "-",
                self._num(r.units) if r.present else "-",
                self._num(r.ok),
                self._num(r.empty),
                self._num(r.failed),
            )
            print("  " + "".join(str(c).ljust(w) for c, w in zip(cells, widths)))
            if r.note:
                print(f"      {r.note}")

        outstanding = sum(r.failed for r in rows if r.failed)
        mined = sum(r.units for r in rows if r.present)
        missing = [r.stage for r in rows if not r.present]

        print(f"\n  {mined:,} unit(s) mined across {len(rows) - len(missing)} artifact(s).")
        if outstanding:
            print(f"  {outstanding:,} unit(s) recorded as failed; re-run that stage to "
                  f"re-attempt them.")
        if missing:
            print(f"  Not mined yet: {', '.join(missing)}")

    def write_csv(self, rows: List[ArtifactCoverage]) -> None:
        path = self.get_output_path()
        try:
            # newline="" is required by the csv module on Windows; without it every row is
            # followed by a blank one.
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
                for r in rows:
                    writer.writerow([
                        r.stage,
                        r.artifact,
                        int(r.present),
                        r.records if r.present else "",
                        r.units if r.present else "",
                        "" if r.ok is None else r.ok,
                        "" if r.empty is None else r.empty,
                        "" if r.failed is None else r.failed,
                        r.duplicates,
                        ";".join(f"{k}={v}" for k, v in sorted(r.status_counts.items())),
                        r.note,
                    ])
            print(f"\n  Written to {path.name}")
        except OSError as e:
            print(f"\n  Could not write {path.name}: {e}")

    # ------------------------------------------------------------------ formatting

    @staticmethod
    def _num(value) -> str:
        """None means the artifact cannot answer that question; zero means it answered zero."""
        return "-" if value is None else f"{value:,}"