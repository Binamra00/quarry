import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


class GitGateway:
    """
    Facade over all raw git invocation.

    Every git command in the pipeline routes through here. Before this class, three
    different call styles were scattered across four files: adapter_subprocess.run_command,
    bare subprocess.run, and subprocess.Popen -- each with its own quoting, cwd handling,
    and error conventions. That is three places to get flag-injection, timeouts, or the
    `-C <repo>` convention subtly wrong.

    This gateway is the single seam. It does NOT know WHY a command runs (acquire a repo,
    resolve a universe, verify a sha) -- that stays in the classes above it. It only knows
    HOW to run git safely and report the result uniformly.

    Design: Facade (structural). It unifies ACCESS to git, not the RESPONSIBILITIES of its
    callers -- RepositoryLoader, CommitUniverse, and Sampler keep their separate jobs and
    simply share this plumbing.
    """

    def __init__(self, repo_path: Optional[Path] = None, default_timeout: int = 600):
        # Optional bound repo: when set, run() injects `-C <repo_path>` automatically so
        # callers don't repeat it. Unbound gateways (e.g. for `git clone`) pass cwd per call.
        self.repo_path = Path(repo_path) if repo_path else None
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------ core

    def run(self, args: List[str], *, cwd: Optional[str] = None,
            timeout: Optional[int] = None, check: bool = False) -> Tuple[bool, str]:
        """
        Run a git command. Returns (ok, output) where output is stdout+stderr stripped.

        args: git subcommand and flags WITHOUT the leading "git" (e.g. ["rev-list","--count","HEAD"]).
        cwd:  overrides the bound repo_path for this call.
        check: if True, raise CalledProcessError on non-zero exit instead of returning (False, ...).
        """
        if args and args[0] == "git":
            raise ValueError("Pass git args WITHOUT the leading 'git' -- the gateway adds it.")

        cmd = ["git"]
        target = cwd or (str(self.repo_path) if self.repo_path else None)
        if target:
            cmd += ["-C", target]
        cmd += args

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout or self.default_timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"TIMEOUT after {timeout or self.default_timeout}s: git {' '.join(args)}"
        except FileNotFoundError:
            return False, "git executable not found on PATH"

        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        ok = proc.returncode == 0
        if check and not ok:
            raise subprocess.CalledProcessError(proc.returncode, cmd, output=out)
        return ok, out

    # ------------------------------------------------------------------ convenience

    def rev_list_count(self, *revs: str) -> int:
        ok, out = self.run(["rev-list", "--count", *revs])
        return int(out) if ok and out.isdigit() else -1

    def commit_exists(self, sha: str) -> bool:
        """True iff sha resolves to a commit object (not a tag/tree/blob)."""
        ok, _ = self.run(["cat-file", "-e", f"{sha}^{{commit}}"])
        return ok

    def merge_base(self, a: str, b: str) -> Optional[str]:
        ok, out = self.run(["merge-base", a, b])
        return out if ok and out else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        ok, _ = self.run(["merge-base", "--is-ancestor", ancestor, descendant])
        return ok

    def rev_parse(self, ref: str) -> Optional[str]:
        ok, out = self.run(["rev-parse", ref])
        return out if ok and out else None