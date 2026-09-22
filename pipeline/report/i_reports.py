"""
What a report is, and what it produces.

WHY THIS REPLACED A TEMPLATE METHOD

    The metrics package used to be built on BaseMetrics, a Template Method declaring
    load -> calculate -> save -> print. That was the right shape when there were several
    reports that differed in all four steps.

    There is now one report. A skeleton with a single implementation is not an abstraction, it
    is a layer -- and it was hiding the fact that the four steps no longer varied by REPORT at
    all. What varies is how a single output artifact is inspected: a plain JSONL is counted, a
    status-bearing JSONL is deduplicated and tallied, a channel has a sidecar state file
    describing whether its collection was ever finished.

    So the varying part became a Strategy over ARTIFACTS (IArtifactProbe), and the report
    became a collector that runs them. The lifecycle that used to be inherited is now four
    ordinary lines in one method.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ArtifactCoverage:
    """
    One row of the report: what a single mined artifact contains.

    IT IS A VALUE, NOT A RENDERING. The same object becomes a CSV row and a console line
    without either format being able to change what it says. The old report built its console
    tree and its JSON payload from separate code paths, so the two could disagree about the
    same run.

    COUNTS THAT DO NOT APPLY ARE None, NOT ZERO

        Only artifacts carrying a status field can report failures. For the others, zero
        failures would be a claim the data does not support -- an unmined stage and a stage
        that mined perfectly would look identical. None renders as '-' and means "this artifact
        cannot answer that question".
    """

    stage: str                      # 'meta', 'ck', 'channel:github/issues'
    artifact: str                   # file name, or the expected one when absent
    present: bool

    records: int = 0                # lines in the file
    units: int = 0                  # distinct units of work; differs from records after retries

    ok: Optional[int] = None        # completed units
    failed: Optional[int] = None    # units recorded as failed, awaiting a retry
    empty: Optional[int] = None     # units that completed with nothing to report

    malformed: int = 0              # lines that would not parse

    status_counts: Dict[str, int] = field(default_factory=dict)
    note: str = ""

    @property
    def duplicates(self) -> int:
        """
        Records beyond one per unit: units that were mined more than once.

        Malformed lines are excluded. They are records that yielded no unit, so counting them
        here would report an unreadable line as a retry -- two different problems with two
        different fixes.
        """
        return max(0, self.records - self.units - self.malformed)


class IArtifactProbe(ABC):
    """
    Strategy: how to inspect one kind of mined output.

    A probe reads; it never writes, never mines, and never repairs. Adding a new output stream
    to the report means adding a probe, not editing the report.
    """

    @abstractmethod
    def inspect(self) -> ArtifactCoverage:
        """Read the artifact and describe what is in it."""


class IReport(ABC):
    """
    The contract RunReportCommand drives.

    Deliberately two methods. A report is a Command's receiver: the command needs a name for
    logging and a way to run it, and nothing else about a report concerns the pipeline.
    """

    @abstractmethod
    def get_tool_name(self) -> str:
        ...

    @abstractmethod
    def run_report(self) -> None:
        ...

    @abstractmethod
    def get_output_path(self) -> Path:
        ...