"""
Which flags belong to which stage, as DATA.

WHY THIS IS A TABLE AND NOT A SEQUENCE OF `if` STATEMENTS

    The previous version of this logic was forty lines of guards preceded by a comment
    drawing the same matrix in ASCII. Two representations of one fact, and only one of them
    was executable -- so the comment could drift from the guards, and the `--help` text drew
    the matrix a third time and could drift from both.

    Here the table IS the rule. The validator reads it, and the help formatter renders it, so
    the three can no longer disagree. Adding a stage is one dictionary entry rather than an
    edit in three files.

WHAT A STAGE DECLARES

    allows      flags accepted at all. Anything else given with this stage is rejected by
                name, before a single commit is read.
    requires    flags that must be present.
    walks_commits
                the stage reads git history, so it MUST be told which commits -- exactly one
                of --universe or --full. This is not a style rule: ledger, refm and the git
                commit channel must walk the SAME commits for their outputs to join, and an
                unstated universe is how a run silently produces records that never link.
    flag_notes  per-flag annotations shown in the help table, for the one case where a flag
                is accepted but does nothing.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple

# Flag names, as the plan and the validator know them (no leading dashes).
VERSION = "version"
UNIVERSE = "universe"
FULL = "full"
SAMPLE = "sample"
PLATFORM = "platform"
CHANNEL = "channel"
BATCH = "batch"

ALL_FLAGS: Tuple[str, ...] = (VERSION, UNIVERSE, FULL, SAMPLE, PLATFORM, CHANNEL, BATCH)

# Pairs that contradict each other regardless of stage. Each entry is
# (flag_a, flag_b, why) and the reason is shown verbatim, because "mutually exclusive" on its
# own never tells anyone which one to drop.
MUTUALLY_EXCLUSIVE: Tuple[Tuple[str, str, str], ...] = (
    (VERSION, UNIVERSE,
     "--version pins the walk to ONE commit; --universe walks the whole grid."),
    (VERSION, SAMPLE,
     "--version mines ONE commit; --sample mines a set of snapshots."),
    (UNIVERSE, FULL,
     "--universe mines the pinned grid; --full mines everything reachable."),
)


@dataclass(frozen=True)
class StageSpec:
    name: str
    summary: str
    allows: FrozenSet[str]
    requires: FrozenSet[str] = frozenset()
    walks_commits: bool = False
    # The channel stage is the one irregular row: it walks commits only on the git platform.
    # Encoded as its own field rather than a general rule language, because one exception does
    # not justify one.
    walks_commits_on_git: bool = False
    flag_notes: Dict[str, str] = field(default_factory=dict)


STAGES: Dict[str, StageSpec] = {
    "meta": StageSpec(
        name="meta",
        summary="repository metadata and commit lineage. Run this FIRST: it defines\n"
                "the commit universe every other miner joins on.",
        allows=frozenset({VERSION}),
    ),
    "ledger": StageSpec(
        name="ledger",
        summary="per-commit evolutionary features -- churn, authorship, co-change.",
        allows=frozenset({VERSION, UNIVERSE, FULL, BATCH}),
        walks_commits=True,
    ),
    "refm": StageSpec(
        name="refm",
        summary="RefactoringMiner: refactoring operations per commit.",
        allows=frozenset({VERSION, UNIVERSE, FULL, BATCH}),
        walks_commits=True,
    ),
    "ck": StageSpec(
        name="ck",
        summary="CK structural metrics at each snapshot. The heaviest miner by far;\n"
                "pair it with --sample.",
        allows=frozenset({VERSION, SAMPLE, BATCH}),
    ),
    "channel": StageSpec(
        name="channel",
        summary="trigger channels -- commits, issues, pull requests, reviews,\n"
                "comments. Needs --platform and --channel.",
        allows=frozenset({VERSION, UNIVERSE, FULL, BATCH, PLATFORM, CHANNEL}),
        requires=frozenset({PLATFORM, CHANNEL}),
        walks_commits_on_git=True,
        flag_notes={VERSION: "no effect"},
    ),
    "report": StageSpec(
        name="report",
        summary="read-only summary of what the miners produced. Run this LAST;\n"
                "it mines nothing.",
        allows=frozenset(),
    ),
}


def stages_allowing(flag: str) -> Tuple[str, ...]:
    """Every stage that accepts `flag`. Used to make rejection messages actionable."""
    return tuple(name for name, spec in STAGES.items() if flag in spec.allows)


# ---------------------------------------------------------------------- help rendering

_COLUMNS = (
    ("--version", (VERSION,)),
    ("--universe/--full", (UNIVERSE, FULL)),
    ("--sample", (SAMPLE,)),
    ("--batch", (BATCH,)),
    ("--platform\n--channel", (PLATFORM, CHANNEL)),
)


def _cell(spec: StageSpec, flags: Tuple[str, ...]) -> str:
    if UNIVERSE in flags and FULL in flags:
        if spec.walks_commits:
            return "REQUIRED"
        if spec.walks_commits_on_git:
            return "REQUIRED (git only)"
    note = next((spec.flag_notes[f] for f in flags if f in spec.flag_notes), None)
    if note:
        return note
    if any(f in spec.requires for f in flags):
        return "REQUIRED"
    if any(f in spec.allows for f in flags):
        return "yes"
    return "no"


def help_table(indent: str = "    ") -> str:
    """
    The flag matrix, rendered from STAGES.

    Generated rather than typed, so the help can never claim a combination the validator
    rejects -- which is the failure this whole module exists to prevent.
    """
    headers = [c[0].split("\n") for c in _COLUMNS]
    widths = [max(len(part) for part in h) + 3 for h in headers]
    name_w = max(len(n) for n in STAGES) + 3

    def row(cells, name=""):
        return (indent + name.ljust(name_w) +
                "".join(c.center(w) for c, w in zip(cells, widths))).rstrip()

    lines = [row([h[0] for h in headers], "stage")]
    if any(len(h) > 1 for h in headers):
        lines.append(row([h[1] if len(h) > 1 else "" for h in headers]))
    lines.append(indent + "-" * (name_w + sum(widths)))
    for name, spec in STAGES.items():
        lines.append(row([_cell(spec, flags) for _, flags in _COLUMNS], name))
    return "\n".join(lines)


def stage_help() -> str:
    """The per-stage description block shown against --stage."""
    width = max(len(n) for n in STAGES) + 2
    out = []
    for name, spec in STAGES.items():
        head, *rest = spec.summary.split("\n")
        out.append(f"{name.ljust(width)}{head}")
        out.extend(" " * width + line for line in rest)
    return "\n".join(out)
