"""
The five ways a channel record reaches a commit.

Each is independent. None short-circuits another, and none is tried "first" -- the union of
what they all find is the answer. Adding a sixth route means adding a class here and listing
it in PRODUCERS; nothing else changes.
"""

from typing import Iterator, List

from pipeline.linkage.i_producers import (IEdgeProducer, LinkEdge, REF_API,
                                          ROUTE_COMMIT_MESSAGE, ROUTE_ISSUE_PR_MERGE,
                                          ROUTE_MERGE_COMMIT, ROUTE_PARENT_NUMBER,
                                          ROUTE_PARENT_PR)

CH_PR = "github.pr"
CH_ISSUE = "github.issue"
CH_REVIEW = "github.pr_review"
CH_COMMENT = "github.comment"


class MergeCommitProducer(IEdgeProducer):
    """
    Pull request -> the commit its merge produced.

    THE ONLY ROUTE THE PLATFORM STATES OUTRIGHT. Every other link in this module is inferred
    from something a human typed. This one is a SHA the API supplied, which is why a pull
    request never needs an issue to reach code, and why PR->commit linkage is strictly more
    reliable than issue->commit linkage.
    """

    pass_number = 1

    @property
    def name(self) -> str:
        return "pull request -> merge commit"

    def produce(self, index) -> Iterator[LinkEdge]:
        for number, sha in index.PR_COMMIT.items():
            edge = self._edge(CH_PR, number, number, sha, ROUTE_MERGE_COMMIT, REF_API, index)
            if edge:
                yield edge


class IssueViaPullRequestProducer(IEdgeProducer):
    """
    Issue -> a pull request that names it -> that pull request's merge commit.

    THE ROUTE THAT MATTERS IN SQUASH-MERGE PROJECTS. Where every pull request lands as a single
    squashed commit, the commit message is written by the merge tool and frequently names
    nothing. The issue reference survives only in the pull request BODY, so a linkage strategy
    that reads commit messages alone badly undercounts those projects while looking fine on
    projects that merge normally.

    Emitted for issue numbers AND pull request numbers: a pull request body can reference
    another pull request, and that is a link like any other.
    """

    pass_number = 1

    @property
    def name(self) -> str:
        return "issue -> pull request -> merge commit"

    def produce(self, index) -> Iterator[LinkEdge]:
        for number, pairs in index.ISSUE_PR.items():
            channel = self._channel_for(number, index)
            if channel is None:
                continue                     # a number nobody mined; nothing to attach to
            for pr_number, ref_kind in pairs:
                sha = index.PR_COMMIT.get(pr_number)
                edge = self._edge(channel, number, number, sha,
                                  ROUTE_ISSUE_PR_MERGE, ref_kind, index)
                if edge:
                    yield edge

    @staticmethod
    def _channel_for(number, index):
        if number in index.issue_numbers:
            return CH_ISSUE
        if number in index.pr_numbers:
            return CH_PR
        return None


class CommitMessageProducer(IEdgeProducer):
    """
    Number -> every commit whose message references it.

    THE WEAKEST ROUTE, AND THE ONLY ONE FOR PROJECTS THAT DO NOT USE PULL REQUESTS. It depends
    entirely on somebody having typed `#123`, which makes it inferred rather than exact -- but
    an issue fixed by a direct push to master has no other way to reach code at all.

    Every referencing commit produces an edge. An issue worked on across three commits was
    genuinely worked on across three commits.
    """

    pass_number = 1

    @property
    def name(self) -> str:
        return "commit message -> number"

    def produce(self, index) -> Iterator[LinkEdge]:
        for number, pairs in index.NUM_COMMIT.items():
            channel = IssueViaPullRequestProducer._channel_for(number, index)
            if channel is None:
                continue
            for sha, ref_kind in pairs:
                edge = self._edge(channel, number, number, sha,
                                  ROUTE_COMMIT_MESSAGE, ref_kind, index)
                if edge:
                    yield edge


class ReviewParentProducer(IEdgeProducer):
    """
    Review comment -> its pull request -> that pull request's merge commit.

    A review comment belongs to a pull request BY DEFINITION -- the API only produces them
    there -- so this is the single route, and it is exact at both hops. An unmerged parent
    leaves the comment nowhere to go, which is correct: there is no commit.

    Note the asymmetry worth keeping in mind downstream. A review comment also carries a file
    path natively, so it can reach a FILE even when its parent never merged. That is a
    different join and belongs to whatever needs it.
    """

    pass_number = 1

    @property
    def name(self) -> str:
        return "review comment -> parent pull request"

    def produce(self, index) -> Iterator[LinkEdge]:
        for review in index.reviews:
            parent = review.get("parent_id")
            rid = review.get("record_id")
            if not parent or not rid:
                continue
            sha = index.PR_COMMIT.get(parent)
            edge = self._edge(CH_REVIEW, rid, parent, sha, ROUTE_PARENT_PR, REF_API, index)
            if edge:
                yield edge


class CommentParentProducer(IEdgeProducer):
    """
    Comment -> whatever its parent already reaches.

    RUNS IN THE SECOND PASS, because it inherits rather than resolves. A comment carries no
    reference of its own; it reaches a commit only through the item it hangs off.

    The parent may be an issue OR a pull request and the payload does not say which -- GitHub
    returns both through the same endpoint, and `issue_url` points at /issues/N either way.
    Resolving that here would cost a request per comment. It is unnecessary: both channels are
    mined, so the parent number appears in one of them, and taking whatever edges that number
    has covers both cases without asking.

    ref_kind is inherited from the parent's edge, so a comment on an issue that a pull request
    merely mentions is not promoted to the strength of one that closes it.
    """

    pass_number = 2

    @property
    def name(self) -> str:
        return "comment -> parent"

    def produce(self, index) -> Iterator[LinkEdge]:
        for comment in index.comments:
            parent = comment.get("parent_id")
            rid = comment.get("record_id")
            if not parent or not rid:
                continue
            for parent_edge in index.number_edges.get(parent, ()):
                edge = self._edge(CH_COMMENT, rid, parent, parent_edge.target_sha,
                                  ROUTE_PARENT_NUMBER, parent_edge.ref_kind, index)
                if edge:
                    yield edge


def all_producers() -> List[IEdgeProducer]:
    return [
        MergeCommitProducer(),
        IssueViaPullRequestProducer(),
        CommitMessageProducer(),
        ReviewParentProducer(),
        CommentParentProducer(),
    ]
