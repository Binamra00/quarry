from abc import ABC, abstractmethod
from typing import Dict, Iterator, Optional

"""
The contract every channel source implements.

A channel source knows HOW to reach one platform and how to normalise its raw shape into the
unified record. It does not detect triggers, does not extract references, and does not resolve
files -- each of those is recomputable downstream and none should require re-mining to change.

Implementations live one file per platform:
    git_sources.py     the local repository
    github_sources.py  the GitHub REST API
"""


class RateLimitExhausted(Exception):
    """
    Raised by a source when the platform's API quota is spent.

    Carries the epoch second at which the quota returns, so the adapter can record it in state
    and report the wait rather than failing opaquely.
    """

    def __init__(self, reset_epoch: int, message: str = ""):
        self.reset_epoch = int(reset_epoch)
        super().__init__(message or f"API quota exhausted; resets at {reset_epoch}")


class IChannelSource(ABC):
    """
    Strategy for fetching one channel's records.

    A source knows HOW to reach a platform and how to normalise its raw shape into the unified
    channel record. It does not know what a trigger is, does not extract references, and does
    not write files -- the adapter does those, once, for every source.

    That split is what keeps the component count at 1 + N rather than N copies of the same
    JSONL-writing, state-tracking boilerplate.
    """

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Stable identifier written onto every record, e.g. 'git.commit', 'github.issue'."""

    @abstractmethod
    def fetch(self, state) -> Iterator[Dict]:
        """
        Yield unified channel records, without the `refs` field.

        The state manager is passed in so a paginated source can resume where it stopped and
        can mark pages complete as it goes. Sources over local data may ignore it.

        Raises:
            RateLimitExhausted: the platform quota ran out mid-fetch. Records already yielded
                are kept; the adapter records the reset time and returns a partial run.
        """

    def estimated_total(self) -> Optional[int]:
        """
        Total records, if it can be known cheaply. None otherwise.

        Local sources can count up front. Paginated remote sources generally cannot without
        spending a request, so they return None and the adapter shows an unbounded count.
        """
        return None


def blank_record(channel_id: str) -> Dict:
    """
    The unified channel record: the fields EVERY channel shares.

    A channel that cannot fill one of these leaves it empty rather than omitting it, so a
    detector can scan `text` and `labels` on any record without knowing its origin.

    Sources may ADD channel-specific fields on top -- a pull request's `merge_commit_sha`, a
    review comment's `diff_line`. These are structural facts only that platform reports, they
    are meaningful only for that channel, and listing them here would put a null
    `merge_commit_sha` on every commit record for no benefit. Consumers reach them with .get().

    A parent's labels are deliberately NOT among these. They are derivable by joining
    `parent_id` to the mined issue or pull request, so storing them would cache data that is
    already present -- and the comment endpoints do not return them anyway.

    WHAT BELONGS HERE, AND WHAT DOES NOT
        A record carries what only the source can supply: the raw text, the platform's own
        labels, and structural facts the API reports (a review comment's file path, an issue's
        closing commit). Anything DERIVABLE from `text` -- references, trigger classifications,
        sentiment -- is deliberately absent.

        The reason is not tidiness. Deriving at mine time freezes the derivation into the mined
        data: change the pattern and you must re-mine, re-spending API quota, to update a field
        that a downstream pass could have recomputed from `text` in milliseconds. Extraction
        also IS detection, and detection is the detector's job -- the same separation that took
        `is_bug_fix` out of the ledger.
    """
    return {
        "record_id": None,        # SHA, issue number, PR number, comment id
        "channel": channel_id,
        "timestamp": None,        # epoch seconds
        "author": None,
        "text": "",               # the raw discourse -- detectors scan this downstream
        "labels": [],             # issues and PRs only; the platform's own classification
        "file_path": None,        # PR review comments only -- the API reports the file directly
        "parent_id": None,        # comments only
        "parent_channel": None,   # comments only
    }
