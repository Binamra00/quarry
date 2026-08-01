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

            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                wait = (2 ** attempt) * 2
                print(f"\n   ⏳ Network error ({type(e).__name__}); retrying in {wait}s "
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

    def paginate(self, endpoint: str, params: Optional[Dict] = None,
                 start_page: int = 1) -> Iterator[Tuple[int, List[Dict]]]:
        """
        Walk a listing endpoint, yielding (page_number, items).

        The page number is yielded so the caller can record it only after the page's records are
        safely written -- a page marked done before its contents are persisted would be skipped
        on resume.

        Ordering is forced to created/asc here rather than left to callers, because
        ChannelStateManager's page-based resumption is only sound under that order.
        """
        q = dict(params or {})
        q.setdefault("per_page", self.PER_PAGE)
        q["sort"] = "created"
        q["direction"] = "asc"

        page = max(1, int(start_page))
        while True:
            q["page"] = page
            url = f"{self.api_base}/repos/{self.owner}/{self.repo}/{endpoint.lstrip('/')}" \
                  f"?{urllib.parse.urlencode(q)}"
            items, headers = self._request(url)

            if not items:
                return

            yield page, items

            # Quota check AFTER yielding: the page just fetched is handed over and recorded, so
            # a resumed run continues from the next page rather than refetching this one.
            remaining = headers.get("x-ratelimit-remaining")
            reset = headers.get("x-ratelimit-reset")
            if remaining is not None and remaining.isdigit() \
                    and int(remaining) <= self.QUOTA_FLOOR and reset:
                raise GitHubRateLimited(int(reset))

            # Termination. The Link header is GitHub's documented signal and is authoritative
            # when present: absence of rel="next" means this was the last page, whether or not
            # it was full. Only when the header is missing entirely do we fall back to the
            # length heuristic.
            #
            # Getting this wrong costs quota rather than correctness -- an over-eager walk just
            # fetches an empty page and stops -- but on a 200-page channel the requests add up.
            if "link" in headers:
                if 'rel="next"' not in headers["link"]:
                    return
            elif len(items) < int(q["per_page"]):
                return

            page += 1