from pathlib import Path
from typing import Dict, Iterator, Optional

from pipeline.utils import adapter_subprocess
from pipeline.scope import CommitUniverse
from pipeline.channels.i_sources import IChannelSource, blank_record

"""
Channel sources backed by the local git repository.
"""


class GitCommitSource(IChannelSource):
    """
    Commit messages, from the local clone.

    SCOPE -- the same commit universe the ledger and RefactoringMiner walked.

        Every channel record reaches files by resolving to a commit and joining the ledger. A
        record for a commit outside the study universe can never join, so mining it adds noise
        to prevalence counts without adding a single linkable event. The universe is resolved
        through the same CommitUniverse the other history walkers use, so the three cannot
        disagree by construction:

            universe_path given  -> [head_sha] + dangling snapshot SHAs   (the pinned grid)
            universe_path None   -> --all                                 (matches metadata)

    WHY THE PINNED FORM IS A FREEZE

        `git rev-list <sha>` walks ANCESTORS, and every commit added after `head_sha` is a
        DESCENDANT. A commit's SHA hashes its parents, so its ancestor set is fixed the moment
        it is created and no later push can enter it. The walk therefore returns the identical
        set however far the clone has advanced -- verified on checkstyle: eleven days and 137
        new commits after mining, the pinned count was still 17,185.

        This is stronger than a date cutoff. `--before` filters on committer date, which is not
        graph position: a rebase restamps dates, a long-lived branch merges with old ones, and
        dates are not even monotonic across a merge-base. A SHA has none of those problems.

    WHY THE JAVA FILTER IS APPLIED HERE

        A commit knows its own files at fetch time, so the filter is free, and a commit touching
        no Java has no Java blast radius to contribute. Text channels cannot do this -- an issue
        has no files until a reference resolves it -- so for those the filter moves to linkage.

        Applying it here also gives a checkable invariant: this source and RefactoringMiner walk
        identical arguments, so their record counts must match per repository.

    No pagination, no quota: this reads a local repository, so `state` is unused.
    """

    # Control characters as separators: they cannot occur in commit messages, unlike the pipes
    # and newlines a message may legitimately contain.
    UNIT = "\x1f"
    RECORD = "\x1e"

    def __init__(self, repo_path: Path, universe_path: str = None):
        self.repo_path = Path(repo_path)
        self.universe = CommitUniverse(self.repo_path.name, universe_path=universe_path)

    @property
    def channel_id(self) -> str:
        return "git.commit"

    def describe(self) -> str:
        return self.universe.describe()

    def verify(self) -> None:
        """Confirm the clone can still reproduce the pinned universe. Raises if it cannot."""
        self.universe.verify_against(self.repo_path)

    def estimated_total(self) -> Optional[int]:
        ok, out = adapter_subprocess.run_command(
            ["git", "rev-list", *self.universe.rev_list_args(), "--count", "--", "*.java"],
            cwd=str(self.repo_path), verbose=False)
        return int(out.strip()) if ok and out.strip().isdigit() else None

    def fetch(self, state=None) -> Iterator[Dict]:
        fmt = self.UNIT.join(["%H", "%ct", "%an", "%ae", "%B"]) + self.RECORD
        cmd = ["git", "log", *self.universe.rev_list_args(),
               f"--format={fmt}", "--", "*.java"]

        ok, output = adapter_subprocess.run_command(
            cmd, cwd=str(self.repo_path), verbose=False, timeout=1800)
        if not ok or not output:
            return

        for chunk in output.split(self.RECORD):
            chunk = chunk.strip("\n\r")
            if not chunk.strip():
                continue
            parts = chunk.split(self.UNIT)
            if len(parts) < 5:
                continue    # malformed line; skip rather than abort the run

            sha, ts, author_name, author_email, message = parts[0], parts[1], parts[2], parts[3], parts[4]

            rec = blank_record(self.channel_id)
            rec["record_id"] = sha.strip()
            rec["timestamp"] = int(ts) if ts.strip().isdigit() else None
            rec["author"] = author_name.strip()
            rec["author_email"] = author_email.strip()
            rec["text"] = message.strip()
            yield rec
