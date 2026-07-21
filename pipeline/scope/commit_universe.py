import hashlib
import json
import subprocess
from pathlib import Path
from typing import List, Optional

from pipeline import config


class CommitUniverse:
    """
    The set of commits a mining adapter (Ledger, RefactoringMiner) must walk.

    TWO MODES, chosen by whether an explicit universe file is supplied:

    FULL  (no --universe flag; universe_path is None)
        Walks `--all`: every branch, tag, and disconnected root -- exactly what the
        MetadataAdapter mines. The adapter is "dumb": it mines the whole repository and
        its commit count equals the metadata source of truth. Nothing is pinned, because
        there is nothing to reproduce -- this is the complete universe.

    EXPLICIT  (--universe versions/adapter_universe_<repo>.json)
        Walks the study grid: HEAD (pinned to the exact head_sha the grid was mined from)
        plus the admitted dangling snapshot SHAs. Bounded and verified, so a run reproduces
        the study's observation universe rather than whatever the clone currently contains.

    Why FULL uses --all rather than HEAD:
        Metadata mines --all, and FULL mode exists to match it. --all includes the
        disconnected pre-import roots (e.g. dubbo 2.0.x-2.3.0) that HEAD cannot reach.

    Why EXPLICIT pins to head_sha rather than the literal "HEAD":
        "HEAD" is a mutable pointer -- it moves when any adapter checks out a tag, and a
        `git fetch` can leave it behind origin. Pinning makes the walk reproduce the grid's
        universe by construction and fails loudly on a too-stale clone.

    Both adapters resolve their universe through this one class, so an explicit run cannot
    have the two miners walk different sets.

    Produced by: rel_tag_mining_v4.ipynb (section 6)
    Consumed by: LedgerAdapter, RefactoringMinerAdapter
    """

    MODE_FULL = "FULL"
    MODE_EXPLICIT = "EXPLICIT"

    def __init__(self, repo_name: str, universe_path: Optional[str] = None):
        self.repo_name = repo_name
        self.mode = self.MODE_FULL if universe_path is None else self.MODE_EXPLICIT

        # EXPLICIT-mode fields (unused in FULL mode)
        self.path: Optional[Path] = None
        self.near_mainline_shas: List[str] = []
        self.head_sha: str = ""
        self.head_commits: int = 0

        if self.mode == self.MODE_EXPLICIT:
            self._load(Path(universe_path))

    # ------------------------------------------------------------------ loading

    def _load(self, given: Path) -> None:
        path = self._resolve(given)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("repo") != self.repo_name:
            raise ValueError(
                f"Universe file repo mismatch: expected '{self.repo_name}', "
                f"found '{data.get('repo')}' in {path.name}"
            )

        shas = data.get("near_mainline_shas", [])
        if not isinstance(shas, list) or not all(isinstance(s, str) for s in shas):
            raise ValueError(f"Malformed 'near_mainline_shas' in {path.name}")

        self.path = path
        self.near_mainline_shas = shas
        self.head_sha = data.get("head_sha", "")
        self.head_commits = int(data.get("head_commits", 0))
        if not self.head_sha:
            raise ValueError(
                f"{path.name} has no 'head_sha'. Re-run rel_tag_mining_v4.ipynb (section 6): "
                f"the walk is pinned to the exact HEAD the grid was mined from."
            )

    def _resolve(self, given: Path) -> Path:
        """
        Resolve the universe file. Accept the path as given; if it is bare (no parent),
        look under the canonical grid directory, then OUTPUTS_PATH as a fallback so a
        misplaced file yields a useful message instead of a bare "not found".
        """
        candidates = []
        if given.parent != Path("."):
            candidates.append(given)                                   # explicit path, use as-is
        else:
            candidates.append(config.GRID_PATH / given.name)          # canonical
            candidates.append(config.OUTPUTS_PATH / given.name)       # fallback

        for i, p in enumerate(candidates):
            if p.exists():
                if i > 0:
                    print(f"   \u26a0\ufe0f  {p.name} resolved from {p.parent.name}/ "
                          f"(canonical location is {candidates[0].parent.name}/).")
                return p

        searched = "\n".join(f"        {p}" for p in candidates)
        raise FileNotFoundError(
            f"\n\u274c --universe was given but the file for '{self.repo_name}' was not found.\n"
            f"   Searched:\n{searched}\n"
            f"   Fix: run rel_tag_mining_v4.ipynb (section 6), or omit --universe to mine the\n"
            f"   full repository (--all, matching metadata)."
        )

    # ------------------------------------------------------------------ walk spec

    def rev_list_args(self) -> List[str]:
        """
        Revision arguments for `git rev-list` / `git log`.

        FULL     -> ["--all"]                          (whole repo, == metadata)
        EXPLICIT -> [head_sha] + near_mainline_shas    (pinned grid universe)
        """
        if self.mode == self.MODE_FULL:
            return ["--all"]
        return [self.head_sha] + self.near_mainline_shas

    def verify_against(self, repo_path) -> None:
        """
        EXPLICIT: confirm the clone can reproduce the grid's history; raise on mismatch.
        FULL: nothing to verify -- the universe IS whatever the repository contains.
        """
        if self.mode == self.MODE_FULL:
            return

        def git(*args):
            return subprocess.run(["git", "-C", str(repo_path), *args],
                                  capture_output=True, text=True)

        if git("cat-file", "-e", f"{self.head_sha}^{{commit}}").returncode != 0:
            raise RuntimeError(
                f"\n\u274c {self.repo_name}: the grid's HEAD ({self.head_sha[:10]}) is not in this clone.\n"
                f"   The release grid was mined from a newer history than the one on disk.\n"
                f"   Fix: git -C <repo> fetch --all --tags --force"
            )

        missing = [s for s in self.near_mainline_shas
                   if git("cat-file", "-e", f"{s}^{{commit}}").returncode != 0]
        if missing:
            raise RuntimeError(
                f"\n\u274c {self.repo_name}: {len(missing)} snapshot commit(s) missing from this "
                f"clone (e.g. {missing[0][:10]}).\n"
                f"   Fix: git -C <repo> fetch --all --tags --force"
            )

        out = git("rev-list", "--count", self.head_sha).stdout.strip()
        local = int(out) if out.isdigit() else -1
        if self.head_commits and local != self.head_commits:
            print(f"   \u26a0\ufe0f  {self.repo_name}: grid recorded {self.head_commits} commits at "
                  f"HEAD, this clone reports {local}. Walk is pinned to the grid's HEAD, so mining "
                  f"is still correct -- but the counts should match; investigate.")

    # ------------------------------------------------------------------ identity

    def fingerprint(self) -> str:
        """
        Stable hash of the universe, stored in batch state so a change is detected.
        FULL mode has no fixed membership (the repo can grow), so it fingerprints the mode
        itself -- switching between FULL and EXPLICIT is what must be caught, and that shows
        up as a fingerprint change.
        """
        if self.mode == self.MODE_FULL:
            return "FULL"
        payload = "|".join([self.head_sha] + sorted(self.near_mainline_shas))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def describe(self) -> str:
        if self.mode == self.MODE_FULL:
            return "universe: FULL (--all, matches the metadata source of truth)"
        n = len(self.near_mainline_shas)
        head = f"grid HEAD {self.head_sha[:10]}"
        if n == 0:
            return f"universe: {head} only (no dangling snapshots)"
        return f"universe: {head} + {n} dangling snapshot commit(s) [fp {self.fingerprint()}]"