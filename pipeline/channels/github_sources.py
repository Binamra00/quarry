from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from pipeline.platforms.github_client import GitHubClient, GitHubRateLimited
from pipeline.channels.i_sources import IChannelSource, RateLimitExhausted, blank_record


def _epoch(iso: Optional[str]) -> Optional[int]:
    """GitHub timestamps are RFC 3339 UTC ('2020-01-01T00:00:00Z')."""
    if not iso:
        return None
    try:
        return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def _number_from_url(url: Optional[str]) -> Optional[int]:
    """'.../repos/o/r/issues/1234' -> 1234. Used to find a comment's parent."""
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _login(user: Optional[Dict]) -> Optional[str]:
    return (user or {}).get("login")


def _label_names(item: Dict) -> list:
    """Labels arrive as objects on issues/PRs and as bare strings on some payloads."""
    out = []
    for l in item.get("labels") or []:
        out.append(l.get("name") if isinstance(l, dict) else str(l))
    return [x for x in out if x]


class _GitHubSource(IChannelSource):
    """
    Shared machinery for every GitHub channel.

    Subclasses declare WHICH endpoint they read and HOW one item becomes a record. Everything
    else -- the client, pagination, page bookkeeping -- is identical and lives here.

    PAGE BOOKKEEPING AND WHY THE ORDER MATTERS
        A page is marked done only after every one of its items has been yielded, which means
        the adapter has already recorded each id. Because mark_page_done flushes, that write
        captures the ids and the page number together.

        Marking the page earlier would risk the opposite: a page recorded as complete whose
        records were never persisted, silently skipped on resume.
    """

    def __init__(self, repo_path: Path, client: Optional[GitHubClient] = None):
        self.repo_path = Path(repo_path)
        self.client = client or GitHubClient(self.repo_path)

    # --- subclass contract ---

    @property
    @abstractmethod
    def endpoint(self) -> str:
        """Path under /repos/{owner}/{repo}/."""

    @property
    def params(self) -> Dict:
        return {}

    @abstractmethod
    def to_record(self, item: Dict) -> Optional[Dict]:
        """One API item -> one unified record, or None to skip it."""

    # --- shared behaviour ---

    def describe(self) -> str:
        return f"{self.client.slug} via {self.endpoint}"

    def verify(self) -> None:
        self.client.check_access()

    def estimated_total(self) -> Optional[int]:
        # A paginated remote does not reveal its size without walking it, and spending a request
        # to guess is not worth it. The adapter falls back to an unbounded count.
        return None

    def fetch(self, state=None) -> Iterator[Dict]:
        start = state.next_page() if state is not None else 1
        try:
            for page, items in self.client.paginate(self.endpoint, self.params, start_page=start):
                for item in items:
                    rec = self.to_record(item)
                    if rec is not None:
                        yield rec
                if state is not None:
                    state.mark_page_done(page)
        except GitHubRateLimited as e:
            # Transport exhaustion becomes the contract's exception here. The client stays free
            # of any dependency on the channel contract, and the adapter catches one exception
            # whichever platform raised it.
            raise RateLimitExhausted(e.reset_epoch) from None


class GitHubIssueSource(_GitHubSource):
    """
    Closed issues.

    THE ENDPOINT RETURNS PULL REQUESTS TOO. In GitHub's data model every pull request is an
    issue, so /issues yields both, distinguished by the presence of a `pull_request` key. Those
    are skipped here and mined properly by GitHubPullRequestSource, which reads /pulls and gets
    the pull-request-specific fields with them.

    CLOSED ONLY. An open issue has no resolving commit, so it cannot reach files and cannot
    receive a blast radius. Mining it would add records the linkage step discards.

    record_id is the issue NUMBER rather than the API's internal id, because `#123` in a commit
    message refers to the number. Using anything else would break the join the channel exists
    to support.
    """

    @property
    def endpoint(self) -> str:
        return "issues"

    @property
    def params(self) -> Dict:
        return {"state": "closed"}

    @property
    def channel_id(self) -> str:
        return "github.issue"

    def to_record(self, item: Dict) -> Optional[Dict]:
        if "pull_request" in item:
            return None                      # a PR; GitHubPullRequestSource handles it
        rec = blank_record(self.channel_id)
        rec["record_id"] = item.get("number")
        rec["timestamp"] = _epoch(item.get("created_at"))
        rec["author"] = _login(item.get("user"))
        rec["text"] = f"{item.get('title') or ''}\n\n{item.get('body') or ''}".strip()
        rec["labels"] = _label_names(item)
        rec["closed_at"] = _epoch(item.get("closed_at"))
        return rec


class GitHubPullRequestSource(_GitHubSource):
    """
    Closed pull requests.

    `merge_commit_sha` IS THE REASON THIS READS /pulls RATHER THAN FILTERING /issues.

        It is a commit SHA supplied by the API, not inferred from text, so a merged pull request
        reaches the ledger directly -- no reference pattern, no ambiguity. That makes PR->commit
        linkage strictly more reliable than issue->commit linkage, which depends on someone
        having typed `#123` in a commit message.

        It is present on closed-unmerged PRs too, where it points at a test merge and means
        nothing; `merged_at` distinguishes the two, so both are recorded and the decision is
        left downstream.
    """

    @property
    def endpoint(self) -> str:
        return "pulls"

    @property
    def params(self) -> Dict:
        return {"state": "closed"}

    @property
    def channel_id(self) -> str:
        return "github.pr"

    def to_record(self, item: Dict) -> Optional[Dict]:
        rec = blank_record(self.channel_id)
        rec["record_id"] = item.get("number")
        rec["timestamp"] = _epoch(item.get("created_at"))
        rec["author"] = _login(item.get("user"))
        rec["text"] = f"{item.get('title') or ''}\n\n{item.get('body') or ''}".strip()
        rec["labels"] = _label_names(item)
        rec["closed_at"] = _epoch(item.get("closed_at"))
        # API-supplied linkage: only the platform knows these.
        rec["merged_at"] = _epoch(item.get("merged_at"))
        rec["merge_commit_sha"] = item.get("merge_commit_sha")
        return rec


class GitHubReviewCommentSource(_GitHubSource):
    """
    Pull request review comments -- the ones attached to a line of a diff.

    THE ONLY TEXT CHANNEL WITH NATIVE FILE LINKAGE. The API reports `path` (and a line), so a
    review comment resolves to a file without any reference resolution at all. Every other text
    channel needs a `#123` to reach code; this one arrives already there.

    If code-level discussion is where refactoring intent surfaces, this is the channel most
    likely to show it, and the one least likely to be lost to unresolvable references.

    REPO-LEVEL ENDPOINT. /pulls/comments returns every review comment in the repository, so this
    costs one page per hundred comments rather than one request per pull request.

    NO JAVA FILTER HERE. Pagination fetches whole pages regardless, so discarding non-Java
    comments saves no requests -- only disk -- while making the filter impossible to change
    without re-mining. `file_path` is stored; the filter is applied downstream for free.
    """

    @property
    def endpoint(self) -> str:
        return "pulls/comments"

    @property
    def channel_id(self) -> str:
        return "github.pr_review"

    def to_record(self, item: Dict) -> Optional[Dict]:
        rec = blank_record(self.channel_id)
        rec["record_id"] = item.get("id")
        rec["timestamp"] = _epoch(item.get("created_at"))
        rec["author"] = _login(item.get("user"))
        rec["text"] = item.get("body") or ""
        rec["file_path"] = item.get("path")          # native file linkage
        rec["parent_id"] = _number_from_url(item.get("pull_request_url"))
        rec["parent_channel"] = "github.pr"
        rec["diff_line"] = item.get("line") or item.get("original_line")
        rec["commit_sha"] = item.get("commit_id")    # the diff this comment was written against
        return rec


class GitHubIssueCommentSource(_GitHubSource):
    """
    Comments on issues and on pull request conversations.

    REPO-LEVEL ENDPOINT. /issues/comments returns every such comment in the repository, so this
    costs one page per hundred comments rather than one request per parent.

    PARENT CHANNEL IS RECORDED AS github.issue, WHICH IS GITHUB'S OWN FRAMING, NOT AN ERROR.
        Because a pull request is an issue, its conversation comments are issue comments, and
        `issue_url` points at /issues/N whether N is an issue or a PR. The payload carries no
        flag distinguishing them.

        Resolving which it is costs nothing downstream: both channels are mined, so parent_id
        either appears among the issues or among the pull requests. Doing it here would mean an
        extra request per comment.

    NO parent_labels FIELD. A parent's labels are derivable by joining parent_id to the mined
    issue or pull request, so caching them here would freeze data that is already available --
    and the endpoint does not return them in any case.

    NO STATE FILTER EXISTS for comments, so comments on open issues arrive too. They are dropped
    at linkage, when their parent turns out not to be among the mined (closed) items.
    """

    @property
    def endpoint(self) -> str:
        return "issues/comments"

    @property
    def channel_id(self) -> str:
        return "github.comment"

    def to_record(self, item: Dict) -> Optional[Dict]:
        rec = blank_record(self.channel_id)
        rec["record_id"] = item.get("id")
        rec["timestamp"] = _epoch(item.get("created_at"))
        rec["author"] = _login(item.get("user"))
        rec["text"] = item.get("body") or ""
        rec["parent_id"] = _number_from_url(item.get("issue_url"))
        rec["parent_channel"] = "github.issue"
        return rec


GITHUB_SOURCES = {
    "issues":     GitHubIssueSource,
    "prs":        GitHubPullRequestSource,
    "pr_reviews": GitHubReviewCommentSource,
    "comments":   GitHubIssueCommentSource,
}