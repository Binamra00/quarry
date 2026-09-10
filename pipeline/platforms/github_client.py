import http.client
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from pipeline import config


class GitHubAccessError(RuntimeError):
    """The API cannot be reached with the configured credentials, or the repo is not visible."""


class GitHubRateLimited(RuntimeError):
    """
    The GitHub hourly quota is spent. Carries the epoch second at which it returns.

    This is a TRANSPORT concern, so it is defined here rather than in the channel contract.
    Keeping it local means this module -- bottom layer, alongside the other plumbing -- imports
    nothing from the domain modules above it. The GitHub source translates it into the
    contract's RateLimitExhausted, which is what the adapter catches.
    """

    def __init__(self, reset_epoch: int):
        self.reset_epoch = int(reset_epoch)
        super().__init__(f"GitHub quota exhausted; resets at {reset_epoch}")


class GitHubClient:
    """
    Facade over the GitHub REST API.

    Every GitHub channel source routes its requests through this one class, so authentication,
    pagination, quota handling and backoff exist in a single place rather than four. It is to
    the GitHub sources what GitGateway is to the local-repository classes: it knows HOW to reach
    the platform, and nothing about WHY.

    THE TOKEN
        Read from config.GITHUB_TOKEN (which reads .env). It is never printed, never written to
        a state file, and never included in an error message -- exception text carries the URL
        and status, never the headers.

        Unauthenticated requests work for public data but are capped at 60 requests/hour against
        5,000 authenticated. That is the difference between mining a corpus in an afternoon and
        not mining it at all, so an unauthenticated client warns loudly.

    PAGINATION ORDER IS A CORRECTNESS CONCERN, NOT A PREFERENCE
        Every listing is requested with sort=created&direction=asc. Sorting by update time would
        reorder items whenever anything is edited, so a run resumed tomorrow could skip records
        it never saw or repeat ones it did. Ascending creation order is stable: new items append
        at the END, leaving already-processed pages untouched.

        This is the assumption ChannelStateManager's page resumption depends on. Changing the
        sort here silently breaks resumption there.

    TWO KINDS OF RATE LIMIT
        The PRIMARY limit is the hourly quota, reported in X-RateLimit-Remaining and reset at
        X-RateLimit-Reset. Exhausting it raises GitHubRateLimited, which the GitHub source
        translates into the channel contract's RateLimitExhausted so the adapter can record it.

        The SECONDARY limit throttles bursts and is independent of the hourly quota. It arrives
        as HTTP 403 with a Retry-After header, and it is not a failure -- it means "slow down".
        This client sleeps and retries rather than aborting a run that still has quota left.
    """

    API_VERSION = "2022-11-28"
    PER_PAGE = 100                 # the API maximum; fewer pages means less quota spent
    QUOTA_FLOOR = 2                # stop with headroom rather than on the last request
    MAX_RETRIES = 4
    TIMEOUT = 30

    def __init__(self, repo_path: Path, token: Optional[str] = None,
                 api_base: Optional[str] = None):
        self.repo_path = Path(repo_path)
        self.owner, self.repo = self._resolve_slug(self.repo_path)
        self._token = token if token is not None else getattr(config, "GITHUB_TOKEN", None)
        self.api_base = (api_base or getattr(config, "GITHUB_API", None)
                         or "https://api.github.com").rstrip("/")

        if not self._token:
            print("   ⚠️  No GITHUB_TOKEN configured. Unauthenticated requests are capped at")
            print("      60/hour (against 5,000 authenticated) and will not finish a corpus.")
            print("      Put GITHUB_TOKEN in .env before a real run.")

    # ------------------------------------------------------------------ repository identity

    @staticmethod
    def _resolve_slug(repo_path: Path) -> Tuple[str, str]:
        """
        owner/repo, read from the clone's origin remote.

        The local directory name is not enough: the folder is `checkstyle` while the API path is
        `checkstyle/checkstyle`, and for a fork or a renamed project the two can differ entirely.
        The remote is authoritative.
        """
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=15).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            raise GitHubAccessError(f"Could not read origin remote for {repo_path}: {e}")

        if not out:
            raise GitHubAccessError(
                f"{repo_path.name} has no origin remote, so its GitHub owner/repo is unknown.")

        # https://github.com/owner/repo(.git)  |  git@github.com:owner/repo(.git)
        m = re.search(r'github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', out)
        if not m:
            raise GitHubAccessError(
                f"origin is not a GitHub remote, so GitHub channels do not apply: {out}")
        return m.group(1), m.group(2)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    # ------------------------------------------------------------------ request plumbing

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
            "User-Agent": "smell-ranker-channel-miner",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, url: str) -> Tuple[List[Dict], Dict[str, str]]:
        """
        One GET, with retries for transient failures and secondary-limit backoff.

        Returns (parsed body, response headers). Raises GitHubRateLimited when the hourly quota
        is spent, and GitHubAccessError for conditions retrying cannot fix.
        """
        last_err = None

        for attempt in range(self.MAX_RETRIES):
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    body = json.loads(resp.read().decode("utf-8"))
                    return (body if isinstance(body, list) else [body]), headers

            except urllib.error.HTTPError as e:
                headers = {k.lower(): v for k, v in (e.headers or {}).items()}
                remaining = headers.get("x-ratelimit-remaining")
                reset = headers.get("x-ratelimit-reset")

                # Primary quota gone. Not retryable within this run.
                if e.code in (403, 429) and remaining is not None and remaining.isdigit() \
                        and int(remaining) == 0 and reset:
                    raise GitHubRateLimited(int(reset))

                # Secondary limit: a burst throttle, not a quota failure. Wait and continue.
                if e.code in (403, 429):
                    wait = int(headers.get("retry-after") or (2 ** attempt) * 5)
                    print(f"\n   ⏳ Secondary rate limit; pausing {wait}s "
                          f"(attempt {attempt + 1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    last_err = e
                    continue

                if e.code == 401:
                    raise GitHubAccessError(
                        "GitHub rejected the credentials (401). Check GITHUB_TOKEN in .env -- "
                        "it may be expired, revoked, or mistyped.")
                if e.code == 404:
                    raise GitHubAccessError(
                        f"{self.slug} returned 404. The repository may be private, renamed, or "
                        f"the endpoint may not exist: {url}")
                if 500 <= e.code < 600:
                    wait = (2 ** attempt) * 2
                    print(f"\n   ⏳ GitHub {e.code}; retrying in {wait}s "
                          f"(attempt {attempt + 1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    last_err = e
                    continue

                raise GitHubAccessError(f"GitHub returned {e.code} for {url}")

            # Everything below is a TRANSPORT failure: the request never produced an HTTP
            # status, so retrying is the correct response.
            #
            # The exception tree here is wider than it looks, and catching URLError alone --
            # as this did originally -- misses most of it:
            #
            #   IncompleteRead        HTTPException   the connection dropped mid-body. Seen on
            #                                         large responses; a 14,000-item page of
            #                                         pull requests is over a megabyte.
            #   ConnectionResetError  OSError         peer closed the socket
            #   TimeoutError          OSError         no response in time
            #   URLError              OSError         DNS failure, refused connection
            #
            # IncompleteRead descends from HTTPException, NOT from URLError, so it belongs to a
            # different branch entirely and was never retryable. ConnectionResetError is an
            # OSError but not a URLError, so it was not caught either. Catching OSError and
            # HTTPException covers both branches; HTTPError is handled above and returns before
            # reaching here, so the broader catch does not swallow real HTTP statuses.
            except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
                wait = (2 ** attempt) * 2
                print(f"\n   ⏳ Transport error ({type(e).__name__}); retrying in {wait}s "
                      f"(attempt {attempt + 1}/{self.MAX_RETRIES})")
                time.sleep(wait)
                last_err = e
                continue

        raise GitHubAccessError(f"Gave up on {url} after {self.MAX_RETRIES} attempts: {last_err}")

    # ------------------------------------------------------------------ public API

    def check_access(self) -> Dict:
        """
        One cheap request confirming the token works and the repository is visible.

        Worth spending before a long run: a bad token discovered on page 1 costs one request,
        discovered on page 400 costs the run.
        """
        url = f"{self.api_base}/repos/{self.owner}/{self.repo}"
        body, headers = self._request(url)
        info = body[0] if body else {}
        remaining = headers.get("x-ratelimit-remaining", "?")
        limit = headers.get("x-ratelimit-limit", "?")
        print(f"   🔑 {self.slug} reachable | quota {remaining}/{limit} remaining"
              f"{'' if self._token else '  (UNAUTHENTICATED)'}")
        return info

    @staticmethod
    def _next_link(headers: Dict[str, str]) -> Optional[str]:
        """
        The rel="next" URL from a Link header, or None if this was the last page.

        Link: <https://api.github.com/...&page=2&after=CURSOR>; rel="next", <...>; rel="last"
        """
        link = headers.get("link")
        if not link:
            return None
        for part in link.split(","):
            segments = part.split(";")
            if len(segments) >= 2 and 'rel="next"' in segments[1]:
                return segments[0].strip().strip("<>")
        return None

    def paginate(self, endpoint: str, params: Optional[Dict] = None,
                 start_page: int = 1,
                 start_url: Optional[str] = None
                 ) -> Iterator[Tuple[int, List[Dict], Optional[str]]]:
        """
        Walk a listing endpoint, yielding (page_number, items, next_url).

        FOLLOWS THE LINK HEADER RATHER THAN CONSTRUCTING page=N.

            This is not a style preference. GitHub caps OFFSET pagination on some endpoints:
            /issues refuses page 101 at per_page=100 with HTTP 422, because that would be the
            10,001st item. /pulls has no such cap, which is why the same client walked 14,505
            pull requests and then failed at exactly 10,000 issues.

            The rel="next" URL carries an `after=<cursor>` alongside page=N, and following it
            verbatim bypasses the offset limit. GitHub's documentation is explicit: "In all
            cases, you can use the URLs in the link header to fetch additional pages of
            results."

            Only the FIRST request is constructed here. Every subsequent one is whatever GitHub
            said comes next.

        RESUMPTION.
            next_url is yielded so the caller can persist it and resume exactly where it
            stopped, cursor included. A caller with no stored URL falls back to start_page,
            which works for any offset below the cap -- so older state files still resume, they
            simply re-derive the cursor once they get deep enough to need it.

        Ordering is forced to created/asc here rather than left to callers, because page-based
        resumption is only sound under that order.
        """
        q = dict(params or {})
        q.setdefault("per_page", self.PER_PAGE)
        q["sort"] = "created"
        q["direction"] = "asc"
        per_page = int(q["per_page"])

        page = max(1, int(start_page))
        if start_url:
            url = start_url
        else:
            q["page"] = page
            url = (f"{self.api_base}/repos/{self.owner}/{self.repo}/{endpoint.lstrip('/')}"
                   f"?{urllib.parse.urlencode(q)}")

        while True:
            items, headers = self._request(url)
            if not items:
                return

            next_url = self._next_link(headers)

            # Yield BEFORE the quota check, so the page just fetched is handed over and recorded;
            # a resumed run then continues from next_url rather than refetching this page.
            yield page, items, next_url

            remaining = headers.get("x-ratelimit-remaining")
            reset = headers.get("x-ratelimit-reset")
            if remaining is not None and remaining.isdigit() \
                    and int(remaining) <= self.QUOTA_FLOOR and reset:
                raise GitHubRateLimited(int(reset))

            # No rel="next" means this was the last page. The length check is a fallback for
            # endpoints that omit the Link header entirely.
            if not next_url:
                return
            if "link" not in headers and len(items) < per_page:
                return

            url = next_url
            page += 1