"""
The command line, and nothing else.

This module knows how to turn a list of strings into a RunPlan. It does NOT know whether the
resulting plan makes sense -- that is validate.py -- and it does not know what any stage does.
Keeping the two apart is what lets the pipeline be driven from a notebook: build a RunPlan,
skip this module entirely.

THE HELP TEXT IS PARTLY GENERATED

    The stage list and the flag matrix come from spec.STAGES, the channel list from
    config.CHANNEL_PLATFORMS, and the command name from how the process was actually started.
    Documentation that is typed out by hand goes stale the first time someone adds a channel
    and forgets; documentation that is rendered cannot.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from pipeline import config
from pipeline.cli import TOOL_NAME, spec
from pipeline.cli.plan import DEFAULT_BATCH, RunPlan


def invocation() -> str:
    """
    How this process was started, so the help can show commands that actually work.

    Installed via the console-script entry point, argv[0] is `quarry` (or `quarry.exe`) and
    that is what the examples should say. Run from a source checkout it is `main.py`, and the
    example must be `python -m pipeline.main` -- `python main.py` fails, because main.py lives
    inside the package and its imports are absolute.
    """
    name = Path(sys.argv[0]).name
    if name.lower() in ("main.py", "__main__.py", "main", ""):
        return "python -m pipeline.main"
    return name[:-4] if name.lower().endswith(".exe") else name


PROG = invocation()

DESCRIPTION = f"""\
{TOOL_NAME} -- a release-level mining pipeline for refactoring trigger analysis.

HOW TO USE IT

  Five decisions, in order. Only the first two are always needed.

    1. WHICH REPOSITORY   --repo <folder-name | github-url>
    2. WHICH MINER        --stage meta|ledger|refm|ck|channel|report
    3. WHICH SCOPE        --full | --universe FILE | --version TAG | --sample FILE
    4. only for channel   --platform git|github
    5. only for channel   --channel commits|issues,prs|all

  ONE MINER PER RUN. There is no 'all' stage: each miner writes its own output and
  keeps its own progress, so they are run one at a time and in any order after meta.

  EVERY MINER RESUMES. Re-run the exact same command and it picks up where it
  stopped -- after an interrupt, a crash, or an exhausted API quota. Nothing is
  mined twice.
"""


def _channel_block() -> str:
    platforms = getattr(config, "CHANNEL_PLATFORMS", {})
    if not platforms:
        return "    (none configured)"
    width = max(len(p) for p in platforms) + 3
    return "\n".join(f"    {p.ljust(width)}{', '.join(chans)}"
                     for p, chans in platforms.items())


def build_epilog() -> str:
    q = PROG
    pad = " " * (len(q) + 1)
    return f"""\
CHANNELS AVAILABLE

{_channel_block()}

  Only CLOSED issues and pull requests are mined. An open issue has no resolving
  commit, so it cannot reach a file and would be discarded at linkage anyway.

WHICH FLAGS GO WITH WHICH STAGE

{spec.help_table()}

  Anything marked 'no' is rejected before a single commit is read, with a message
  naming the stages the flag does belong to. 'no effect' means it is accepted and
  changes nothing: a channel walk is scoped by --universe/--full on the git
  platform, and by the API itself on github.

EXAMPLES

  # 1. metadata first -- it establishes the commit universe everything else joins on
  {q} --repo checkstyle --stage meta

  # 2. commit walkers, pinned to the study grid
  {q} --repo checkstyle --stage ledger --universe adapter_universe_checkstyle.json
  {q} --repo checkstyle --stage refm   --universe adapter_universe_checkstyle.json

  # 3. CK, at the release snapshots only (it is far too slow to run per commit)
  {q} --repo checkstyle --stage ck --sample rel_hist_checkstyle.json

  # 4. trigger channels
  {q} --repo checkstyle --stage channel --platform git --channel commits \\
  {pad}--universe adapter_universe_checkstyle.json
  {q} --repo checkstyle --stage channel --platform github --channel issues,prs
  {q} --repo checkstyle --stage channel --platform github --channel all --batch 200

  # 5. read back what the miners produced
  {q} --repo checkstyle --stage report

  # first time on a new machine: a URL clones the repository into the workspace.
  # This toy project is small enough to run every stage end to end in a couple of
  # minutes, which makes it the right thing to try first.
  {q} --repo https://github.com/danilofes/refactoring-toy-example.git --stage meta

BEFORE A GITHUB RUN

  Put GITHUB_TOKEN in .env. Unauthenticated requests are capped at 60 an hour
  against 5,000 authenticated, which is the difference between mining a corpus in
  an afternoon and not mining it at all.
"""


class CliParser:
    """Builds a RunPlan from argv."""

    def build(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=PROG,
            description=DESCRIPTION,
            epilog=build_epilog(),
            formatter_class=argparse.RawTextHelpFormatter,
            add_help=False,
        )

        # ------------------------------------------------------------ 1. target
        g_target = parser.add_argument_group("1. TARGET -- what to mine")
        g_target.add_argument("--repo",
                              metavar="NAME|URL",
                              # [UX] Default kept for backward compatibility with old scripts.
                              default="toy_project",
                              help="A folder name under the workspace, or a GitHub URL.\n"
                                   "A URL is cloned on first use and reused after that.\n"
                                   "(default: toy_project)\n ")

        # ------------------------------------------------------------ 2. stage
        g_stage = parser.add_argument_group(
            "2. STAGE -- which miner to run (pick exactly one)")
        g_stage.add_argument("--stage",
                             metavar="STAGE",
                             choices=list(spec.STAGES),
                             required=True,
                             help=spec.stage_help() + "\n ")

        # ------------------------------------------------------------ 3. scope
        g_scope = parser.add_argument_group(
            "3. SCOPE -- which commits or snapshots\n"
            "               (ledger, refm and the git channel MUST be given "
            "--universe or --full)")
        g_scope.add_argument("--universe",
                             metavar="FILE",
                             default=None,
                             help="Mine only the pinned study grid in FILE, e.g.\n"
                                  "adapter_universe_checkstyle.json. USE THIS for anything\n"
                                  "the study depends on: it is the only way every miner is\n"
                                  "guaranteed to have walked the same commits.\n ")
        g_scope.add_argument("--full",
                             action="store_true",
                             help="Mine every commit the clone can reach (git --all).\n"
                                  "NOT frozen -- two runs on different days walk different\n"
                                  "histories, and the output will not join a pinned run.\n"
                                  "For verification and exploration only. Prints a warning.\n ")
        g_scope.add_argument("--version",
                             metavar="TAG|SHA",
                             default=None,
                             help="Check out one tag or commit and mine only that point.\n"
                                  "Cannot be combined with --universe or --sample.\n ")
        g_scope.add_argument("--sample",
                             metavar="FILE",
                             default=None,
                             help="CK ONLY. Mine just the snapshots listed in a rel_hist\n"
                                  "manifest, e.g. rel_hist_checkstyle.json -- the release\n"
                                  "grid rather than every commit.\n ")

        # ------------------------------------------------------------ 4. channel
        g_chan = parser.add_argument_group(
            "4. CHANNEL -- required for --stage channel, ignored otherwise")
        g_chan.add_argument("--platform",
                            metavar="PLATFORM",
                            default=None,
                            help="git      reads the local clone. Offline, no token.\n"
                                 "github   reads the GitHub API. Needs GITHUB_TOKEN in .env.\n ")
        g_chan.add_argument("--channel",
                            metavar="LIST|all",
                            default=None,
                            help="Comma-separated, e.g. --channel issues,prs.\n"
                                 "'all' means every channel the platform provides.\n"
                                 "Each channel gets its own output file and its own\n"
                                 "resumable state, so one failing leaves the rest intact.\n"
                                 "See CHANNELS AVAILABLE below for the names.\n ")

        # ------------------------------------------------------------ execution
        g_exec = parser.add_argument_group("EXECUTION")
        g_exec.add_argument("--batch",
                            metavar="N",
                            type=int,
                            # No default. The absence of the flag and an explicit value equal
                            # to the default are different facts, and the validator needs to
                            # tell them apart; the default is applied by RunPlan instead.
                            default=None,
                            help=f"Stop after N records, then exit cleanly; the next run\n"
                                 f"resumes. Useful for trying a github channel against a few\n"
                                 f"hundred real records without spending an hour of quota.\n"
                                 f"0 = unlimited. (default: {DEFAULT_BATCH})\n ")
        g_exec.add_argument("-h", "--help",
                            action="help",
                            help="Show this message and exit.")

        return parser

    def parse(self, argv: Optional[Sequence[str]] = None) -> RunPlan:
        args = self.build().parse_args(argv)
        return RunPlan(
            repo=args.repo,
            stage=args.stage.lower(),
            version=args.version,
            universe=args.universe,
            full=args.full,
            sample=args.sample,
            platform=args.platform,
            channels=args.channel,
            batch=args.batch,
        )