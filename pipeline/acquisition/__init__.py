"""
Repository acquisition: getting a target repo onto disk in the right state.

RepositoryLoader (Facade) resolves a --repo argument (URL or local name) to a local
path, cloning/fetching/syncing as needed. GitClient is the low-level clone helper it
delegates to. GitGateway is the shared seam all git invocation routes through.

Called at pipeline SETUP time (main.py), before any mining begins.
"""
from pipeline.acquisition.loader import RepositoryLoader
from pipeline.acquisition.git_gateway import GitGateway

__all__ = ["RepositoryLoader", "GitGateway"]