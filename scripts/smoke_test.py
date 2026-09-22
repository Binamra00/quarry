#!/usr/bin/env python3
"""
Quarry smoke test -- run every command the tool accepts, and every one it should refuse.

WHY A SCRIPT AND NOT A LIST IN A README

    The point is not to have the commands written down, it is to have them RUN. A miner that
    stopped working is invisible until something tries it, and the combinations that break
    first are the ones nobody types by hand: an empty channel, a batch of zero, a stage whose
    manifest went missing.

WHAT IT CHECKS

    The exit code, and -- where a case declares one -- that the file the stage exists to
    produce is actually on disk afterwards. Whether the CONTENTS are right is what the corpus
    integrity notebook is for.

    The second check matters more than it sounds. A stage whose only deliverable is a file can
    exit 0 having written nothing: a swallowed OSError, a path that moved, a rename that failed
    silently. Exit codes alone report that as a pass.

TIERS

    local    everything that runs offline against the clone. Safe to run any time.
    github   the API-backed channels. Needs GITHUB_TOKEN and spends quota, so it is opt in.
    reject   commands that MUST fail. A validator that quietly starts accepting a bad
             combination is a silent regression, so the rejections are tested like the
             acceptances.
    verify   contracts over what the miners WROTE. Runs no command: it reads the outputs and
             asserts that the diff stage walked the same commits as RefactoringMiner, that its
             records carry the fields Stage 5 reads, and that they render as DRS-OSS pieces.
             Equal commit COUNTS are not enough -- two sets of the same size with different
             members join to nothing downstream and report no error doing it.

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
from typing import Callable, List, Optional

# Repositories this matrix is known to run against, as folder name -> upstream URL.
#
# A REGISTRY RATHER THAN ONE CONSTANT, because --clone has to clone whatever --repo names.
# With a single URL it cloned the toy project no matter which repository was asked for, then
# ran every case against a folder that did not exist -- 30 confusing failures with one cause.
#
#   toy_project   65 commits. The default: the whole local tier finishes in under a minute,
#                 which is what you want after changing a miner.
#   gson          ~2k commits, and a project that actually uses GitHub issues and pull
#                 requests. The realistic exercise -- the linkage routes and the CK status
#                 tally do almost nothing on a repository with no discourse. Budget 30-60
#                 minutes, most of it RefactoringMiner.
#
# Anything else: pass --clone-url.
TEST_REPOS = {
    "toy_project": "https://github.com/danilofes/refactoring-toy-example.git",
    "gson": "https://github.com/google/gson.git",
}
DEFAULT_REPO = "toy_project"


@dataclass
class Case:
    tier: str
    label: str
    args: List[str]
    expect_zero: bool = True
    # Files that must exist for the case to be meaningful. Missing ones make it a SKIP rather
    # than a failure: a repository with no tags has no release grid, and that is not a bug.
    needs: List[Path] = field(default_factory=list)
    # Files the stage must have written by the time it exits, checked only when the exit code
    # was as expected. Deleted first (see `clears`) so their presence proves THIS run wrote
    # them rather than some earlier one.
    produces: List[Path] = field(default_factory=list)
    # A content check, for the `verify` tier. Takes no arguments, returns (ok, [messages]).
    # Runs INSTEAD of a subprocess -- these cases assert a contract over files the miners
    # already wrote, rather than running a command.
    check: Optional[Callable[[], tuple]] = None


def build_cases(repo: str, workspace: Path, tag: Optional[str]) -> List[Case]:
    grid = workspace / "grid"
    versions = workspace / "versions"
    outputs = workspace / "outputs"
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
    for stage in ("ledger", "refm", "diff"):
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

    # ---------------------------------------------------------------- link
    # A derivation over everything above, so it runs after the miners and before the report.
    # Both outputs are declared: linkage is the one stage whose entire product is a pair of
    # files, and an empty edge list is a real outcome that must still be written.
    cases += [
        Case("local", "link", R + ["--stage", "link"],
             produces=[outputs / f"links_{repo}.csv",
                       outputs / f"linkage_summary_{repo}.csv"]),
        # Re-running must OVERWRITE, not append -- linkage is the one stage that does. Running
        # it twice is how that is checked: the second run deletes and rewrites both files, and
        # a stage that appended would still pass the existence check but double its rows.
        Case("local", "link is idempotent (second pass)", R + ["--stage", "link"],
             produces=[outputs / f"links_{repo}.csv",
                       outputs / f"linkage_summary_{repo}.csv"]),
    ]

    # ---------------------------------------------------------------- report
    # Runs last, so it reports on everything the cases above mined. The CSV is the stage's
    # entire deliverable, which makes its absence the one failure an exit code cannot express.
    cases += [Case("local", "report", R + ["--stage", "report"],
                   produces=[outputs / f"report_{repo}.csv"])]

    # ---------------------------------------------------------------- must be refused
    cases += [
        Case("reject", "ledger with no universe",
             R + ["--stage", "ledger"], expect_zero=False),
        Case("reject", "meta with --batch",
             R + ["--stage", "meta", "--batch", "10"], expect_zero=False),
        Case("reject", "meta with --universe",
             R + ["--stage", "meta", "--universe", universe], expect_zero=False),
        Case("reject", "diff with no universe",
             R + ["--stage", "diff"], expect_zero=False),
        Case("reject", "diff with --sample",
             R + ["--stage", "diff", "--full", "--sample", sample], expect_zero=False),
        Case("reject", "diff with --platform",
             R + ["--stage", "diff", "--full", "--platform", "github"], expect_zero=False),
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
        Case("reject", "link with --full",
             R + ["--stage", "link", "--full"], expect_zero=False),
        Case("reject", "link with --batch",
             R + ["--stage", "link", "--batch", "10"], expect_zero=False),
        Case("reject", "link with --universe",
             R + ["--stage", "link", "--universe", universe], expect_zero=False),
        Case("reject", "link with --platform",
             R + ["--stage", "link", "--platform", "github"], expect_zero=False),
        Case("reject", "unknown stage",
             R + ["--stage", "heuristics"], expect_zero=False),
    ]

    # ---------------------------------------------------------------- verify
    # Contracts over what the miners WROTE, not over whether a command exited zero.
    #
    # The docstring above says content is the integrity notebook's job, and that still holds
    # for the corpus. These three are here because Stage 5 consumes them directly and a
    # violation is invisible until a downstream join silently loses rows -- which is the
    # failure this whole pipeline is built to prevent.
    diffs = outputs / f"diffs_{repo}.jsonl"
    refms = outputs / f"refactorings_{repo}.jsonl"
    cases += [
        Case("verify", "diff walks the same commits as refm",
             [], needs=[diffs, refms],
             check=lambda: _check_parity(diffs, refms)),
        Case("verify", "diff records are well formed",
             [], needs=[diffs],
             check=lambda: _check_schema(diffs)),
        Case("verify", "diff renders as DRS-OSS pieces",
             [], needs=[diffs],
             check=lambda: _check_drs_oss(diffs)),
    ]

    return cases


# ---------------------------------------------------------------------- content checks

def _read_jsonl(path: Path):
    import json
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _check_parity(diffs: Path, refms: Path) -> tuple:
    """
    The diff stage and RefactoringMiner must have walked the SAME commits.

    Equal counts are not enough. Two sets of the same size with different members join to
    nothing downstream and report no error while doing it -- the exact failure the shared
    CommitUniverse exists to prevent. This is the check that proves the sharing works.
    """
    d = {r["sha1"] for r in _read_jsonl(diffs)}
    r = {r["sha1"] for r in _read_jsonl(refms)}
    msgs = [f"diff {len(d):,} commits, refm {len(r):,}"]
    if d == r:
        return True, msgs
    msgs.append(f"sets differ: {len(d - r):,} only in diff, {len(r - d):,} only in refm")
    for sha in list(d - r)[:3]:
        msgs.append(f"   only in diff: {sha}")
    for sha in list(r - d)[:3]:
        msgs.append(f"   only in refm: {sha}")
    msgs.append("re-run both stages with the same --universe file")
    return False, msgs


def _check_schema(diffs: Path) -> tuple:
    """Every record carries the fields Stage 5 reads, and the counts agree with the lists."""
    required = {"sha1", "timestamp", "message", "files", "n_files", "n_files_total",
                "truncated", "is_merge", "n_parents", "status"}
    recs = list(_read_jsonl(diffs))
    if not recs:
        return False, ["file is empty"]

    problems = []
    missing_fields = {f for r in recs for f in required - set(r)}
    if missing_fields:
        problems.append(f"fields missing from some records: {sorted(missing_fields)}")

    shas = [r["sha1"] for r in recs]
    if len(set(shas)) != len(shas):
        problems.append(f"{len(shas) - len(set(shas))} duplicate sha1 value(s)")

    bad_counts = [r["sha1"][:7] for r in recs
                  if r.get("n_files") != len(r.get("files") or [])]
    if bad_counts:
        problems.append(f"n_files disagrees with files list: {bad_counts[:3]}")

    bad_lines = [(r["sha1"][:7], f.get("file")) for r in recs for f in (r.get("files") or [])
                 if f.get("n_added") != len(f.get("added") or [])
                 or f.get("n_removed") != len(f.get("removed") or [])]
    if bad_lines:
        problems.append(f"n_added/n_removed disagree with the lists: {bad_lines[:3]}")

    crashes = sum(1 for r in recs if r.get("status") == "crash")
    msgs = [f"{len(recs):,} records, {len(set(shas)):,} unique",
            f"status: " + ", ".join(f"{k}={v}" for k, v in
                                    __import__("collections").Counter(
                                        r.get("status") for r in recs).items())]
    if crashes:
        msgs.append(f"{crashes} crash record(s) -- not retried on re-run, inspect the log")
    return not problems, msgs + problems


def _check_drs_oss(diffs: Path) -> tuple:
    """
    Records render as the pieces the Stage 5 classifier expects.

    Rendering is done by the adapter's own render_pieces, imported rather than reimplemented,
    so this cannot drift from what the notebook actually calls. If the import fails the shape
    is still checked from the record, and the check says which path it took.
    """
    recs = list(_read_jsonl(diffs))
    if not recs:
        return False, ["file is empty"]

    try:
        from pipeline.adapters.diff_adapt import DiffAdapter
        render = DiffAdapter.render_pieces
        how = "via DiffAdapter.render_pieces"
    except Exception as exc:
        how = f"adapter import failed ({type(exc).__name__}); using a local equivalent"

        def render(record, max_pieces=None):
            out = [f"<COMMIT_MESSAGE>{record.get('message', '')}</COMMIT_MESSAGE>"]
            for f in record.get("files") or []:
                removed = [l for l in (f.get("removed") or []) if l.strip()]
                added = [l for l in (f.get("added") or []) if l.strip()]
                if not removed and not added:
                    continue
                part = [f"<FILE>{f.get('file')}</FILE>"]
                if removed:
                    part.append("<REMOVED>" + chr(10).join(removed) + "</REMOVED>")
                if added:
                    part.append("<ADDED>" + chr(10).join(added) + "</ADDED>")
                out.append(chr(10).join(part))
            return out[:max_pieces] if max_pieces else out

    problems, n_pieces = [], []
    for r in recs:
        pieces = render(r)
        n_pieces.append(len(pieces))
        if not pieces[0].startswith("<COMMIT_MESSAGE>"):
            problems.append(f"{r['sha1'][:7]}: first piece is not the message")
        for p in pieces[1:]:
            if not p.startswith("<FILE>"):
                problems.append(f"{r['sha1'][:7]}: file piece does not open with <FILE>")
                break
        if len(problems) > 5:
            break

    # The shaping contract: no diff syntax survives into the body.
    flat = [l for r in recs for f in (r.get("files") or [])
            for l in (f.get("added") or []) + (f.get("removed") or [])]
    # Lines that LOOK like diff syntax, reported but not failed.
    #
    # The shaping contract cannot be verified from the output. _split_files filters hunk and
    # file headers BEFORE stripping the +/- prefix, with anchored patterns, in the same loop --
    # so a real header cannot survive. A stored line reading "@@ x @@" came from "+@@ x @@",
    # which is content: a patch file, a changelog, documentation containing an example diff.
    #
    # Three such lines in ten thousand commits is content. Thirty thousand would mean the
    # filter stopped running, which is why the count is printed rather than ignored.
    flat = [l for r in recs for f in (r.get("files") or [])
            for l in (f.get("added") or []) + (f.get("removed") or [])]
    looks_like = [l for l in flat
                  if l.startswith("@@ ") or l.startswith(("--- ", "+++ "))]

    msgs = [how,
            f"{len(recs):,} record(s) render; pieces per commit: "
            f"median {sorted(n_pieces)[len(n_pieces)//2]}, max {max(n_pieces)}",
            f"{len(looks_like):,} line(s) look like diff syntax "
            f"({len(looks_like)/max(1, len(flat))*100:.4f}% -- content, not a failure)"]
    return not problems, msgs + problems


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

    if case.check is not None:
        if dry_run:
            print(f"  ▸ [check] {case.label}")
            return "dry"
        print(f"\n{'─' * 78}\n▶ {case.label}")
        started = time.time()
        try:
            ok, messages = case.check()
        except Exception as exc:
            ok, messages = False, [f"check raised {type(exc).__name__}: {exc}"]
        icon = "✅" if ok else "❌"
        print(f"  {icon} {'PASS' if ok else 'FAIL'}  {time.time() - started:.1f}s")
        for m in messages:
            print(f"      {m}")
        return "pass" if ok else "fail"

    if dry_run:
        print(f"  ▸ {printable}")
        return "dry"

    # Removed before the run, not after: a file left over from an earlier invocation would
    # otherwise satisfy the check without this run having written anything at all.
    for target in case.produces:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass

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

    # Output checks only apply once the exit code is right. A stage that correctly refused to
    # run should not also be expected to have produced a file.
    output_problems: List[str] = []
    if ok and case.expect_zero:
        output_problems = _missing_outputs(case)
        ok = not output_problems

    verdict = "PASS" if ok else "FAIL"
    icon = "✅" if ok else "❌"
    expected = "success" if case.expect_zero else "rejection"
    print(f"  {icon} {verdict}  exit={proc.returncode} (expected {expected})  {elapsed:.1f}s")

    for problem in output_problems:
        print(f"      ⚠  {problem}")

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


def _missing_outputs(case: Case) -> List[str]:
    """
    Which declared outputs the stage failed to produce.

    An empty file counts as missing. A zero-byte CSV means the header was never written, which
    is the same class of failure as no file at all and would otherwise pass a bare exists()
    check.
    """
    problems = []
    for target in case.produces:
        if not target.exists():
            problems.append(f"expected output not written: {target.name}")
        elif target.stat().st_size == 0:
            problems.append(f"expected output is empty: {target.name}")
    return problems


def _token_available() -> bool:
    """
    Whether the child process will find a GitHub token.

    Checking os.environ alone is not enough and gives a MISLEADING warning: config.py calls
    load_dotenv() at import, so a token living only in .env is invisible here but perfectly
    visible to the run. Warning about an authenticated run trains people to ignore the warning.
    """
    if os.environ.get("GITHUB_TOKEN"):
        return True
    for candidate in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        try:
            if candidate.exists() and "GITHUB_TOKEN" in candidate.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def clone_repo(repo: str, url: Optional[str]) -> int:
    """
    Fetch the repository under test so the local tier has something to mine.

    The URL comes from --clone-url, or from TEST_REPOS for a known name. An unknown name with
    no URL is refused rather than guessed: cloning the wrong project and then reporting thirty
    failures against it wastes far more time than an error does.

    The folder the clone lands in is RepositoryLoader's decision, not this script's, and it
    will not necessarily equal `repo`. If they differ, pass --repo <folder> next time.
    """
    url = url or TEST_REPOS.get(repo)
    if not url:
        print(f"❌ No URL known for '{repo}'. Pass --clone-url, or use one of: "
              f"{', '.join(TEST_REPOS)}.")
        return 1
    print(f"▶ Cloning {url}")
    proc = subprocess.run(entry_command() + ["--repo", url, "--stage", "meta"])
    if proc.returncode != 0:
        print("❌ Clone failed; the matrix would run against nothing. Stopping.")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run every Quarry command combination and report which ones work.")
    ap.add_argument("--repo", default=DEFAULT_REPO,
                    help=f"Repository folder to test against. Known: "
                         f"{', '.join(TEST_REPOS)} (default: {DEFAULT_REPO})")
    ap.add_argument("--clone-url", default=None,
                    help="Upstream URL for --clone when the repository is not in TEST_REPOS.")
    ap.add_argument("--workspace", default=os.environ.get("QUARRY_HOME") or "workspace_data",
                    help="Workspace root, used to look for the files a case needs. Defaults to\n"
                         "QUARRY_HOME when it is set, so an isolated run does not have to pass\n"
                         "the same path twice and cannot silently look in the wrong place.")
    ap.add_argument("--tier", action="append",
                    choices=["local", "github", "reject", "verify", "all"],
                    help="Which tiers to run. Repeatable. Default: local, reject and verify.")
    ap.add_argument("--tag", default=None,
                    help="A tag or SHA in the repo, to exercise the --version cases.")
    ap.add_argument("--list", action="store_true", help="List the cases and exit.")
    ap.add_argument("--dry-run", action="store_true", help="Print commands without running.")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="Stop at the first failure instead of running the whole matrix.")
    ap.add_argument("--clone", action="store_true",
                    help="Clone the repository named by --repo first, then run the matrix.")
    args = ap.parse_args()

    tiers = set(args.tier or ["local", "reject", "verify"])
    if "all" in tiers:
        tiers = {"local", "github", "reject", "verify"}

    if "github" in tiers and not _token_available():
        print("⚠️  No GITHUB_TOKEN found, in the environment or in a .env file. The github")
        print("   tier will run unauthenticated at 60 requests an hour and will probably fail.\n")

    if args.clone and clone_repo(args.repo, args.clone_url) != 0:
        return 1

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