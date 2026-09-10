"""
One invocation of the pipeline, as a value.

WHY NOT PASS THE ARGPARSE NAMESPACE AROUND

    A Namespace is whatever the CLI happened to define. Threading it into the factory, the
    validator and the workspace couples all three to the shape of the command line, so the
    pipeline can only be driven from a terminal -- calling it from a notebook means
    fabricating a fake Namespace.

    A RunPlan is the same information with a declared shape. The CLI builds one; a notebook
    can build one directly; everything downstream reads the same object either way.

WHY IT IS FROZEN

    A plan is decided once and then acted on. Nothing downstream should be able to quietly
    change the universe or the batch size half way through a run. The validator returns a NEW
    plan with resolved file paths rather than mutating this one (dataclasses.replace).

`batch` IS None WHEN THE FLAG WAS NOT GIVEN

    The old code tested `args.batch != 50` to mean "the user passed --batch", so an explicit
    `--batch 50` on a stage that forbids batching slipped through. The absence of a flag and a
    value that happens to equal the default are different facts, and only None can express the
    first.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple

from pipeline import config
from pipeline.cli import TOOL_NAME, spec

DEFAULT_BATCH = 50


@dataclass(frozen=True)
class RunPlan:
    repo: str
    stage: str

    version: Optional[str] = None
    universe: Optional[str] = None
    full: bool = False
    sample: Optional[str] = None
    platform: Optional[str] = None
    channels: Optional[str] = None      # raw, as typed: "issues,prs" or "all"
    batch: Optional[int] = None         # None = --batch not given

    # Filled in by the validator once the files have been found on disk.
    universe_path: Optional[Path] = None
    sample_path: Optional[Path] = None

    # ------------------------------------------------------------------ derived

    @property
    def spec(self) -> spec.StageSpec:
        return spec.STAGES[self.stage]

    @property
    def given_flags(self) -> frozenset:
        """
        The flags actually supplied, by name.

        `full` is a store_true, so its absence is False rather than None; every other flag is
        absent as None. Both are handled here so the validator never has to care which kind a
        flag is.
        """
        present = {
            spec.VERSION: self.version,
            spec.UNIVERSE: self.universe,
            spec.FULL: self.full or None,
            spec.SAMPLE: self.sample,
            spec.PLATFORM: self.platform,
            spec.CHANNEL: self.channels,
            spec.BATCH: self.batch,
        }
        return frozenset(name for name, value in present.items() if value is not None)

    @property
    def platform_key(self) -> str:
        return (self.platform or "").lower()

    @property
    def walks_commits(self) -> bool:
        """
        Whether this run reads git history, and therefore owes an explicit universe.

        The channel stage answers differently depending on its platform: mining commits walks
        history, mining issues does not.
        """
        s = self.spec
        return s.walks_commits or (s.walks_commits_on_git and self.platform_key == "git")

    @property
    def effective_batch(self) -> int:
        """The batch size to actually use. 0 or below means unlimited; the factory widens it."""
        return DEFAULT_BATCH if self.batch is None else self.batch

    @property
    def requested_channels(self) -> Tuple[str, ...]:
        """`--channel issues,prs` -> ('issues', 'prs'). Not expanded; 'all' stays 'all'."""
        if not self.channels:
            return ()
        return tuple(c.strip().lower() for c in self.channels.split(",") if c.strip())

    @property
    def known_channels(self) -> Tuple[str, ...]:
        """Every channel this plan's platform declares, or () for an unknown platform."""
        return tuple(config.CHANNEL_PLATFORMS.get(self.platform_key, ()))

    def resolved_channels(self) -> Tuple[str, ...]:
        """
        The channel names to actually mine, with 'all' expanded.

        Expansion happens HERE rather than in the factory so the validator and the factory
        cannot disagree about what 'all' meant. config.CHANNEL_PLATFORMS stays the single place
        a platform's channels are listed: adding one there makes it part of 'all' with no other
        edit.
        """
        requested = self.requested_channels
        if requested == ("all",):
            return self.known_channels
        return requested

    def with_paths(self, universe_path: Optional[Path],
                   sample_path: Optional[Path]) -> "RunPlan":
        return replace(self, universe_path=universe_path, sample_path=sample_path)

    # ------------------------------------------------------------------ presentation

    def warnings(self) -> list:
        """Anything the user should read before trusting the output of this run."""
        if not self.full:
            return []
        bar = "=" * 74
        return [
            "", bar,
            "⚠️  FULL MODE -- READ THIS BEFORE RELYING ON THE OUTPUT",
            bar,
            "   The walk is --all: every commit this clone can reach, right now.",
            "",
            "   THERE IS NO FREEZE. The clone is synced from origin on every run, so a run",
            "   today and a run tomorrow walk different histories. Nothing pins them.",
            "",
            "   THE UNIVERSES WILL NOT ALIGN. Any miner run with --universe walked the pinned",
            "   grid. Records produced here that fall outside it cannot join those outputs --",
            "   they are not dropped with an error, they simply never match.",
            "",
            "   FOR FORECASTING OR PREDICTION THIS IS UNSAFE. Downstream joins assume every",
            "   miner saw the same commits. Mixed universes inflate prevalence denominators",
            "   and silently lose events at the join, with no failure to alert you.",
            "",
            "   Use --full only to verify against metadata (ledger == metadata) or to explore.",
            "   For anything the study depends on, use --universe.",
            bar,
        ]

    def scope_description(self) -> str:
        if self.version:
            return f"SINGLE VERSION ({self.version})"
        if self.universe:
            return f"PINNED ({self.universe})"
        if self.full:
            return "FULL (--all) — NOT FROZEN"
        if self.sample:
            return f"SAMPLED ({self.sample})"
        return "n/a"

    def announce(self) -> None:
        """
        Echo the decisions back before any work starts.

        Printed BEFORE acquisition rather than after, so a mistyped stage or universe is
        visible without waiting for a clone.
        """
        print(f"🚀 Starting {TOOL_NAME}")
        for line in config.describe():
            print(line)
        print(f"🎯 Repository: {self.repo}")
        print(f"🎯 Stage: {self.stage.upper()}")
        if self.walks_commits or self.version or self.sample:
            print(f"🎯 Scope: {self.scope_description()}")
        if self.stage == "channel":
            print(f"🎯 Channels: {self.platform} -> {', '.join(self.resolved_channels())}")
        if spec.BATCH in self.spec.allows:
            limit = self.effective_batch
            print(f"🎯 Batch limit: {'unlimited' if limit <= 0 else limit}")
        for line in self.warnings():
            print(line)