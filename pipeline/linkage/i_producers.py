"""
What a link is, and what produces one.

WHY EDGES RATHER THAN A RESOLVED FIELD ON EACH RECORD

    An earlier design resolved each channel record to ONE commit through a precedence chain:
    the exact route first, then the inferred ones, stopping at the first hit. That answers
    "which commit did this issue produce", and it is the wrong question. An issue referenced by
    three commits was genuinely addressed by three commits; picking one discards two real
    observations, and picking it from an unordered set made the choice differ between runs.

    A link is therefore an EDGE, and a record may have as many as the evidence supports.
    Producers do not compete and none short-circuits: each contributes every edge it can find,
    labelled with the route that found it, and the results are unioned.

    Two consequences worth knowing before reading the numbers:

      - COVERAGE IS NOW TWO FIGURES. "Reached" counts records with at least one edge; "edges"
        counts the links themselves. One issue with three commits is one reached record and
        three edges. They will not agree, and neither is wrong.

      - A RECORD CAN LINK ACROSS RELEASE INTERVALS. An issue mentioned in commits six months
        apart produces edges into two intervals. That is signal, not noise, but any window
        logic downstream has to decide whether it takes every edge or only those inside its
        window.

    Because the output is a set rather than an ordered search, it is reproducible by
    construction: no iteration order can change it.

LINKS POINT AT THE FULL COMMIT UNIVERSE, NOT THE LEDGER

    A target is any commit in the clone, as recorded by the metadata stage. Membership in the
    ledger, the RefactoringMiner output and the CK grid is carried as flags on the edge, so
    narrowing to any of them is a filter rather than a re-run. Resolving against the ledger
    directly would bake one study's universe into the evidence and make every other view
    impossible to recover.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional

# Route names. The route says HOW a link was found, and exact-versus-inferred is derivable from
# it, so no second column carries that and the two cannot drift apart.
ROUTE_MERGE_COMMIT = "merge_commit_sha"    # exact: the API named the commit
ROUTE_ISSUE_PR_MERGE = "issue_pr_merge"    # inferred: a PR body names the issue, the PR merged
ROUTE_COMMIT_MESSAGE = "commit_message"    # inferred: a commit message names the number
ROUTE_PARENT_PR = "parent_pr_merge"        # exact: a review comment's parent PR merged
ROUTE_PARENT_NUMBER = "parent_number"      # inherited: a comment takes its parent's edges

EXACT_ROUTES = frozenset({ROUTE_MERGE_COMMIT, ROUTE_PARENT_PR})

# Reference kinds, strongest first. Used to break ties when the same edge is found twice.
REF_API = "api"
REF_RANK = {REF_API: 0, "closes": 1, "mentions": 2}


@dataclass(frozen=True)
class LinkEdge:
    """
    One piece of evidence that a channel record refers to a commit.

    Frozen and narrow on purpose. This is an EDGE LIST, not a copy of the records: the text,
    author and labels already live in the mined channel file, keyed by the same record_id.
    Copying them here would duplicate megabytes and go stale the moment a channel is re-mined.
    """

    source_channel: str      # 'github.issue', 'github.pr', 'github.pr_review', 'github.comment'
    source_id: int           # record_id in the mined channel file -- the join key back
    resolved_via: int        # the number actually resolved; parent_id for comments and reviews
    target_sha: str          # a commit present in the metadata universe
    route: str
    ref_kind: str            # 'api', 'closes', 'mentions'

    @property
    def key(self) -> tuple:
        """
        Identity for deduplication.

        ref_kind is excluded: it is the tie-breaker between two findings of the SAME edge, not
        part of what makes them different edges.
        """
        return (self.source_channel, self.source_id, self.target_sha, self.route)

    @property
    def is_exact(self) -> bool:
        return self.route in EXACT_ROUTES


class IEdgeProducer(ABC):
    """
    Strategy: one way of getting from a channel record to a commit.

    TWO PASSES, DECLARED RATHER THAN ORDERED BY ACCIDENT

        Comments and review comments carry no reference of their own -- they reach a commit
        only through the item they belong to. So they cannot run until the producers that
        resolve issue and pull request numbers have finished.

        `pass_number` states that dependency instead of leaving it to the order of a list. The
        adapter runs pass 1, indexes its results by number, then runs pass 2. Within a pass,
        producers are independent and order is irrelevant.
    """

    pass_number: int = 1

    @property
    @abstractmethod
    def name(self) -> str:
        """Short label for logging."""

    @abstractmethod
    def produce(self, index) -> Iterator[LinkEdge]:
        """Every edge this producer can find. May yield nothing."""

    @staticmethod
    def _edge(source_channel: str, source_id, resolved_via, target_sha: Optional[str],
              route: str, ref_kind: str, index) -> Optional[LinkEdge]:
        """
        Build an edge, or None when the target is not a commit this clone has.

        A SHA that resolves to nothing in the metadata universe is not a link. It is counted as
        a dropped candidate so the summary can distinguish "no reference was made" from "a
        reference was made to a commit we do not have" -- correct behaviour and a real gap look
        identical in a percentage.
        """
        if not target_sha:
            return None
        if target_sha not in index.all_commits:
            index.dropped_absent += 1
            return None
        return LinkEdge(source_channel=source_channel, source_id=int(source_id),
                        resolved_via=int(resolved_via), target_sha=target_sha,
                        route=route, ref_kind=ref_kind)
