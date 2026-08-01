import sys
from typing import List
from pathlib import Path
from pipeline import config
from pipeline.adapters.i_adapters import IAdapter

# Every adapter is lazy-loaded inside create_adapters. A channel-only run should not import
# RefactoringMiner, and a metadata run should not import CK.

class ToolFactory:
    """
    Factory Method Pattern with Lazy Loading.

    One STAGE per run -- there is no "all". Each call builds the adapters for the requested
    stage. universe_path scopes the history walkers (ledger, refm); CK sampling is applied
    separately by the caller via set_sampling_filter().

    The channel stage is the one that returns more than a single adapter: `--channel
    issues,prs` mines two channels in one invocation, each as its own IAdapter, so the command
    and execution machinery needs no change to handle them.
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = None,
                        universe_path: str = None, platform: str = None,
                        channels: str = None) -> List[IAdapter]:
        adapters = []
        stage = stage.lower()

        if batch_size is None or batch_size <= 0:
            batch_size = sys.maxsize

        # RefactoringMiner -- history walker; universe_path scopes the walk.
        if stage == "refm":
            from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
            adapters.append(RefactoringMinerAdapter(target_repo_path, universe_path=universe_path))

        # CK -- structural metrics; sampling is applied by the caller (set_sampling_filter).
        elif stage == "ck":
            from pipeline.adapters.ck_adapt import CkAdapter
            adapters.append(CkAdapter(target_repo_path, batch_size))

        # Evolutionary Ledger -- history walker; universe_path scopes the walk.
        elif stage == "ledger":
            from pipeline.adapters.ledger_adapt import LedgerAdapter
            adapters.append(LedgerAdapter(target_repo_path, batch_size, universe_path=universe_path))

        # Trigger channels -- one adapter per requested channel, each driven by a source
        # strategy that knows how to reach that platform.
        elif stage == "channel":
            from pipeline.adapters.channel_adapt import ChannelAdapter
            for name in ToolFactory._parse_channels(channels):
                source = ToolFactory._build_source(platform, name, target_repo_path,
                                                   universe_path=universe_path)
                adapters.append(ChannelAdapter(target_repo_path, platform, name, source,
                                               batch_size=batch_size))

        return adapters

    # ------------------------------------------------------------------ channel helpers

    @staticmethod
    def _parse_channels(channels: str) -> List[str]:
        """`--channel issues,prs,comments` -> ['issues', 'prs', 'comments']."""
        if not channels:
            raise ValueError("The 'channel' stage requires --channel (e.g. --channel commits).")
        names = [c.strip().lower() for c in channels.split(",") if c.strip()]
        if not names:
            raise ValueError("--channel was given but contained no channel names.")
        return names

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
        """
        if not platform:
            raise ValueError("The 'channel' stage requires --platform (git or github).")
        platform = platform.lower()

        if platform == "git":
            from pipeline.channels.git_sources import GitCommitSource
            if channel != "commits":
                raise ValueError(
                    f"Unknown git channel '{channel}'. The git platform provides: commits")
            return GitCommitSource(target_repo_path, universe_path=universe_path)

        if platform == "github":
            from pipeline.channels.github_sources import GITHUB_SOURCES
            cls = GITHUB_SOURCES.get(channel)
            if cls is None:
                raise ValueError(
                    f"Unknown github channel '{channel}'. "
                    f"Available: {', '.join(GITHUB_SOURCES)}")
            # One client per source. Each carries its own quota accounting, and the sources are
            # mined as separate adapters with separate state, so sharing one buys nothing.
            return cls(target_repo_path)

        raise ValueError(f"Unknown platform '{platform}'. Available: git, github")