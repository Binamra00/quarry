#!/usr/bin/env python3
"""
Quarry smoke test -- run every command the tool accepts, and every one it should refuse.

WHY A SCRIPT AND NOT A LIST IN A README

    The point is not to have the commands written down, it is to have them RUN. A miner that
    stopped working is invisible until something tries it, and the combinations that break
    first are the ones nobody types by hand: an empty channel, a batch of zero, a stage whose
    manifest went missing.

WHAT IT CHECKS

    Only the exit code. A stage that finishes is reported as passing; whether it mined the
    right things is what the corpus integrity notebook is for. That is enough to catch the
    failures this is aimed at -- an import error, a broken flag, a miner that crashes on an
    empty repository, a validator that stopped rejecting something.

TIERS

    local    everything that runs offline against the clone. Safe to run any time.
    github   the API-backed channels. Needs GITHUB_TOKEN and spends quota, so it is opt in.
    reject   commands that MUST fail. A validator that quietly starts accepting a bad
             combination is a silent regression, so the rejections are tested like the
             acceptances.

USAGE

    python scripts/smoke_test.py --list
    python scripts/smoke_test.py --tier local
    python scripts/smoke_test.py --tier local --tier reject
    python scripts/smoke_test.py --tier all --repo refactoring-toy-example
    python scripts/smoke_test.py --dry-run          # print the commands, run nothing

    The first run against a fresh workspace should be:

        python scripts/smoke_test.py --clone
"""

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# The upstream the toy clone comes from, and the folder it lives under in the workspace.
# They differ: the clone was placed at repos/toy_project, which is also --repo's default, so
# the matrix runs against it with no arguments at all.
TOY_URL = "https://github.com/danilofes/refactoring-toy-example.git"
TOY_NAME = "toy_project"


@dataclass
class Case:
    tier: str
    label: str
    args: List[str]
    expect_zero: bool = True
    # Files that must exist for the case to be meaningful. Missing ones make it a SKIP rather
    # than a failure: a repository with no tags has no release grid, and that is not a bug.
    needs: List[Path] = field(default_factory=list)


def build_cases(repo: str, workspace: Path, tag: Optional[str]) -> List[Case]:
    grid = workspace / "grid"
    versions = workspace / "versions"
    universe = f"adapter_universe_{repo}.json"
    sample = f"rel_hist_{repo}.json"
    universe_file = grid / universe
    sample_file = versions / sample

    R = ["--repo", repo]
    cases: List[Case] = []

    # ---------------------------------------------------------------- meta
    # Runs first because the other miners join on the commit universe it establishes, not
    # because it writes the manifest files. adapter_universe_<repo>.json and
    # rel_hist_<repo>.json come from the release-tag mining notebook, so on a repository the
    # notebook has never been run against -- the toy example included -- the pinned and
    # sampled cases below stay SKIPped no matter how many times the matrix is run. That is the
    # correct outcome, not a gap in coverage.
    cases += [
        Case("local", "meta", R + ["--stage", "meta"]),
    ]
    if tag:
        cases += [Case("local", "meta at a pinned version",
                       R + ["--stage", "meta", "--version", tag])]

    # ---------------------------------------------------------------- commit walkers
    for stage in ("ledger", "refm"):
        cases += [
            Case("local", f"{stage} full history", R + ["--stage", stage, "--full"]),
            Case("local", f"{stage} full history, batch 10",
                 R + ["--stage", stage, "--full", "--batch", "10"]),
            Case("local", f"{stage} full history, unlimited batch",
                 R + ["--stage", stage, "--full", "--batch", "0"]),
            Case("local", f"{stage} pinned universe",
                 R + ["--stage", stage, "--universe", universe], needs=[universe_file]),
            Case("local", f"{stage} pinned universe, batch 10",
                 R + ["--stage", stage, "--universe", universe, "--batch", "10"],
                 needs=[universe_file]),
        ]
        if tag:
            cases += [Case("local", f"{stage} single version",
                           R + ["--stage", stage, "--version", tag])]

    # ---------------------------------------------------------------- ck
    cases += [
        Case("local", "ck every commit", R + ["--stage", "ck"]),
        Case("local", "ck every commit, batch 5", R + ["--stage", "ck", "--batch", "5"]),
        Case("local", "ck release grid",
             R + ["--stage", "ck", "--sample", sample], needs=[sample_file]),
        Case("local", "ck release grid, batch 5",
             R + ["--stage", "ck", "--sample", sample, "--batch", "5"], needs=[sample_file]),
    ]
    if tag:
        cases += [Case("local", "ck single version", R + ["--stage", "ck", "--version", tag])]

    # ---------------------------------------------------------------- git channel
    cases += [
        Case("local", "channel git/commits full",
             R + ["--stage", "channel", "--platform", "git", "--channel", "commits", "--full"]),
        Case("local", "channel git/commits full, batch 25",
             R + ["--stage", "channel", "--platform", "git", "--channel", "commits",
                  "--full", "--batch", "25"]),
        Case("local", "channel git/commits pinned",
             R + ["--stage", "channel", "--platform", "git", "--channel", "commits",
                  "--universe", universe], needs=[universe_file]),
        Case("local", "channel git/all",
             R + ["--stage", "channel", "--platform", "git", "--channel", "all", "--full"]),
    ]

    # ---------------------------------------------------------------- github channels
    # Each channel separately, because they fail separately: /issues hits a 10,000-item offset
    # cap, /issues-comments silently stops at 30,000, /pulls has neither. One combined case
    # would hide which of them broke.
    for ch in ("issues", "prs", "pr_reviews", "comments"):
        cases += [Case("github", f"channel github/{ch}",
                       R + ["--stage", "channel", "--platform", "github",
                            "--channel", ch, "--batch", "50"])]
    cases += [
        Case("github", "channel github, two at once",
             R + ["--stage", "channel", "--platform", "github",
                  "--channel", "issues,prs", "--batch", "50"]),
        Case("github", "channel github/all",
             R + ["--stage", "channel", "--platform", "github",
                  "--channel", "all", "--batch", "50"]),
        Case("github", "channel github resumes (second pass)",
             R + ["--stage", "channel", "--platform", "github",
                  "--channel", "issues", "--batch", "50"]),
    ]

    # ---------------------------------------------------------------- report
    cases += [Case("local", "report", R + ["--stage", "report"])]

    # ---------------------------------------------------------------- must be refused
    cases += [
        Case("reject", "ledger with no universe",
             R + ["--stage", "ledger"], expect_zero=False),
        Case("reject", "meta with --batch",
             R + ["--stage", "meta", "--batch", "10"], expect_zero=False),
        Case("reject", "meta with --universe",
             R + ["--stage", "meta", "--universe", universe], expect_zero=False),
        Case("reject", "ck with --universe",
             R + ["--stage", "ck", "--universe", universe], expect_zero=False),
        Case("reject", "--universe and --full together",
             R + ["--stage", "ledger", "--universe", universe, "--full"], expect_zero=False),
        Case("reject", "--version and --sample together",
             R + ["--stage", "ck", "--version", "v1", "--sample", sample], expect_zero=False),
        Case("reject", "channel with no platform",
             R + ["--stage", "channel", "--channel", "issues"], expect_zero=False),
        Case("reject", "channel with no channel",
             R + ["--stage", "channel", "--platform", "github"], expect_zero=False),
        Case("reject", "unknown platform",
             R + ["--stage", "channel", "--platform", "gitlab", "--channel", "issues"],
             expect_zero=False),
        Case("reject", "unknown channel name",
             R + ["--stage", "channel", "--platform", "github", "--channel", "bogus"],
             expect_zero=False),
        Case("reject", "'all' mixed with a named channel",
             R + ["--stage", "channel", "--platform", "github", "--channel", "all,issues"],
             expect_zero=False),
        Case("reject", "--universe on a github channel",
             R + ["--stage", "channel", "--platform", "github", "--channel", "issues",
                  "--universe", universe], expect_zero=False),
        Case("reject", "--full on a github channel",
             R + ["--stage", "channel", "--platform", "github", "--channel", "issues",
                  "--full"], expect_zero=False),
        Case("reject", "--full on report",
             R + ["--stage", "report", "--full"], expect_zero=False),
        Case("reject", "missing universe manifest",
             R + ["--stage", "ledger", "--universe", "no_such_universe.json"],
             expect_zero=False),
        Case("reject", "unknown stage",
             R + ["--stage", "heuristics"], expect_zero=False),
    ]

    return cases


# ---------------------------------------------------------------------- running

def entry_command() -> List[str]:
    """
    How to invoke the tool.

    Prefers the installed console script when it is on PATH, so an installed package is tested
    the way a user would run it; falls back to the module form for a source checkout.
    """
    from shutil import which
    if which("quarry"):
        return ["quarry"]
    return [sys.executable, "-m", "pipeline.main"]


def run_case(case: Case, base: List[str], dry_run: bool) -> str:
    cmd = base + case.args
    printable = " ".join(cmd)

    missing = [p for p in case.needs if not p.exists()]
    if missing:
        print(f"  ⏭  SKIP  {case.label}")
        print(f"           needs {missing[0].name}, which does not exist yet")
        return "skip"

    if dry_run:
        print(f"  ▸ {printable}")
        return "dry"

    print(f"\n{'─' * 78}\n▶ {case.label}\n  $ {printable}")
    started = time.time()
    # encoding is pinned rather than left to the locale. subprocess with text=True decodes
    # using the platform's preferred encoding, which on Windows is cp1252 -- so a child that
    # correctly emits UTF-8 comes back as mojibake, or raises. PYTHONUTF8/PYTHONIOENCODING
    # cover the same ground from the child's side, for a child that predates the stream fix in
    # pipeline/__init__.py.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          errors="replace", env=env)
    elapsed = time.time() - started

    ok = (proc.returncode == 0) == case.expect_zero
    verdict = "PASS" if ok else "FAIL"
    icon = "✅" if ok else "❌"
    expected = "success" if case.expect_zero else "rejection"
    print(f"  {icon} {verdict}  exit={proc.returncode} (expected {expected})  {elapsed:.1f}s")

    if not ok:
        # Only on failure, and only the tail: the head of a mining run is a banner.
        for line in (proc.stdout or "").strip().splitlines()[-15:]:
            print(f"      | {line}")
        # Tracebacks are printed WHOLE. Slicing the last N characters off one cuts the
        # exception type and the innermost frame -- the two lines that say what went wrong --
        # and leaves a fragment like "stderr: fig", which is worse than printing nothing.
        stderr = (proc.stderr or "").strip()
        if stderr:
            print("      | --- stderr ---")
            for line in stderr.splitlines():
                print(f"      | {line}")

    return "pass" if ok else "fail"


def clone_toy() -> None:
    """
    Fetch the toy repository so the local tier has something to mine.

    The folder a URL clone lands in is decided by RepositoryLoader, not by this script, and it
    will not necessarily be TOY_NAME. If the two differ, pass --repo <folder> on the next run
    rather than assuming.
    """
    print("▶ Cloning the toy repository so the local tier has something to mine")
    subprocess.run(entry_command() + ["--repo", TOY_URL, "--stage", "meta"])


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run every Quarry command combination and report which ones work.")
    ap.add_argument("--repo", default=TOY_NAME,
                    help=f"Repository folder to test against (default: {TOY_NAME})")
    ap.add_argument("--workspace", default="workspace_data",
                    help="Workspace root, used to look for manifests (default: workspace_data)")
    ap.add_argument("--tier", action="append", choices=["local", "github", "reject", "all"],
                    help="Which tiers to run. Repeatable. Default: local and reject.")
    ap.add_argument("--tag", default=None,
                    help="A tag or SHA in the repo, to exercise the --version cases.")
    ap.add_argument("--list", action="store_true", help="List the cases and exit.")
    ap.add_argument("--dry-run", action="store_true", help="Print commands without running.")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="Stop at the first failure instead of running the whole matrix.")
    ap.add_argument("--clone", action="store_true",
                    help="Clone the toy repository first, then run the matrix.")
    args = ap.parse_args()

    tiers = set(args.tier or ["local", "reject"])
    if "all" in tiers:
        tiers = {"local", "github", "reject"}

    if "github" in tiers and not os.environ.get("GITHUB_TOKEN"):
        print("⚠️  GITHUB_TOKEN is not set in the environment. The github tier will run")
        print("   unauthenticated at 60 requests an hour and will probably fail.\n")

    if args.clone:
        clone_toy()

    cases = [c for c in build_cases(args.repo, Path(args.workspace), args.tag)
             if c.tier in tiers]

    if args.list:
        for c in cases:
            marker = " " if c.expect_zero else "✗"
            print(f"  [{c.tier:<6}]{marker} {c.label}")
            print(f"           {' '.join(entry_command() + c.args)}")
        return 0

    print(f"Quarry smoke test -- {len(cases)} case(s), tiers: {', '.join(sorted(tiers))}")
    base = entry_command()
    print(f"Invoking: {' '.join(base)}\n")

    tally = {"pass": 0, "fail": 0, "skip": 0, "dry": 0}
    failures = []
    for case in cases:
        result = run_case(case, base, args.dry_run)
        tally[result] += 1
        if result == "fail":
            failures.append(case.label)
            if args.stop_on_fail:
                break

    print(f"\n{'═' * 78}")
    print(f"  passed {tally['pass']}   failed {tally['fail']}   skipped {tally['skip']}")
    for label in failures:
        print(f"    ❌ {label}")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())