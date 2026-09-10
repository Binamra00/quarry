import sys
from pathlib import Path
from typing import List

from pipeline.commands.i_commands import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand
from pipeline.commands.report_cmd import RunReportCommand
from pipeline.cli.plan import RunPlan

# Every adapter is lazy-loaded inside create_commands. A channel-only run should not import
# RefactoringMiner, and a metadata run should not import CK.


class PipelineFactory:
    """
    Factory Method with lazy loading: (plan, repo) -> the commands that plan implies.

    ONE STAGE PER RUN. There is no "all". Each call builds the commands for the requested
    stage, and the caller runs them in order.

    IT RETURNS COMMANDS, NOT ADAPTERS

        It used to return adapters, which left the caller to wrap them, to construct the
        metadata adapter itself, to resolve the CK sample itself, and to run the reports
        outside the command list entirely. Four construction sites for one concept, three of
        them in the entry point.

        Everything a stage needs is assembled here, so the entry point has one call and no
        knowledge of what any stage is made of.

    WHY SAMPLING IS RESOLVED HERE

        set_sampling_filter is construction-time configuration: it reroutes CK's output file
        and rebuilds its progress state. Doing it in the caller meant the object was returned
        half configured and only worked if the caller remembered the second step.

    WHY THE REPORT STAGES ARE HERE TOO

        `report` is a stage like any other, and `refm` produces a report as part of its own
        completion. Both are commands; neither needs a special path.
    """

    @staticmethod
    def create_commands(plan: RunPlan, repo: Path) -> List[IPipelineCommand]:
        stage = plan.stage
        batch = PipelineFactory._batch_size(plan)
        universe = str(plan.universe_path) if plan.universe_path else None

        # Metadata -- git lineage. Defines the commit universe the other miners join on.
        if stage == "meta":
            from pipeline.adapters.metadata_adapt import MetadataAdapter
            return [RunToolCommand(MetadataAdapter(repo))]

        # Evolutionary Ledger -- history walker; universe scopes the walk.
        if stage == "ledger":
            from pipeline.adapters.ledger_adapt import LedgerAdapter
            return [RunToolCommand(
                LedgerAdapter(repo, batch, universe_path=universe))]

        # RefactoringMiner -- history walker, plus its own completion report.
        if stage == "refm":
            from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
            from pipeline.metrics.refm_mets import RefmMetrics
            return [
                RunToolCommand(RefactoringMinerAdapter(repo, universe_path=universe)),
                RunReportCommand(RefmMetrics(repo)),
            ]

        # CK -- structural metrics, optionally restricted to a release grid.
        if stage == "ck":
            from pipeline.adapters.ck_adapt import CkAdapter
            adapter = CkAdapter(repo, batch)
            PipelineFactory._apply_sampling(adapter, plan, repo)
            return [RunToolCommand(adapter)]

        # Trigger channels -- one adapter per requested channel, each driven by a source
        # strategy that knows how to reach that platform, each with its own resumable state.
        if stage == "channel":
            from pipeline.adapters.channel_adapt import ChannelAdapter
            commands = []
            for name in plan.resolved_channels():
                source = PipelineFactory._build_source(
                    plan.platform_key, name, repo, universe_path=universe)
                commands.append(RunToolCommand(
                    ChannelAdapter(repo, plan.platform_key, name, source, batch_size=batch)))
            return commands

        # Universe report -- read-only, run after mining.
        if stage == "report":
            from pipeline.metrics.report_mets import ReportMetrics
            return [RunReportCommand(ReportMetrics(repo))]

        raise ValueError(f"No commands defined for stage '{stage}'.")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _batch_size(plan: RunPlan) -> int:
        """0 or below means unlimited; expressed as maxsize so adapters need no special case."""
        batch = plan.effective_batch
        return sys.maxsize if batch <= 0 else batch

    @staticmethod
    def _apply_sampling(adapter, plan: RunPlan, repo: Path) -> None:
        """
        Restrict CK to the snapshots in a rel_hist manifest.

        The manifest is read here rather than in the entry point because the result is part of
        constructing the adapter, not a decision about the run: set_sampling_filter reroutes the
        output file and rebuilds the progress state against it.
        """
        if not plan.sample_path:
            return
        from pipeline.scope import Sampler
        print(f"🎯 Sampling Mode: ON (reading target tags from {plan.sample_path.name})")
        sampler = Sampler(repo, plan.sample_path.name)
        adapter.set_sampling_filter(sampler.get_priority_shas())

    @staticmethod
    def _build_source(platform: str, channel: str, target_repo_path: Path,
                      universe_path: str = None):
        """
        (platform, channel) -> the source strategy that fetches it.

        Sources are imported lazily: the GitHub ones pull in an HTTP client that a purely local
        run has no reason to load.

        universe_path applies only to the git platform. Issues, pull requests and comments are
        not commits and cannot be bounded by a commit SHA; the pinned universe still constrains
        them, but at LINKAGE -- a record whose reference resolves outside the universe simply
        never joins the ledger.

        THE RAISES BELOW ARE ASSERTIONS, NOT USER MESSAGES. An unknown platform or channel is
        rejected by StageValidator long before construction, so reaching one of these means the
        validator has a hole rather than that the user typed something wrong.
        """
        if platform == "git":
            from pipeline.channels.git_sources import GitCommitSource
            if channel != "commits":
                raise ValueError(
                    f"Unknown git channel '{channel}' reached the factory; "
                    f"StageValidator should have rejected it.")
            return GitCommitSource(target_repo_path, universe_path=universe_path)

        if platform == "github":
            from pipeline.channels.github_sources import GITHUB_SOURCES
            cls = GITHUB_SOURCES.get(channel)
            if cls is None:
                raise ValueError(
                    f"Unknown github channel '{channel}' reached the factory; "
                    f"StageValidator should have rejected it. "
                    f"Available: {', '.join(GITHUB_SOURCES)}")
            # One client per source. Each carries its own quota accounting, and the sources are
            # mined as separate adapters with separate state, so sharing one buys nothing.
            return cls(target_repo_path)

        raise ValueError(f"Unknown platform '{platform}' reached the factory.")


# The class no longer returns tools, so the old name is misleading. Kept as an alias so any
# script or notebook still importing ToolFactory keeps working.
ToolFactory = PipelineFactory