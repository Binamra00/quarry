"""
Repository acquisition: turning a --repo argument into a local clone in the right state.

RepositoryLoader is a Facade. It resolves a URL or a folder name to a path, clones when the repo
is absent, and syncs an existing clone to origin -- fetching AND resetting the local branch,
since `git fetch` alone moves refs/remotes/* and leaves refs/heads/* behind, which is how a
pipeline silently mines a months-old history.

Called once at SETUP time by main.py, before any stage runs.

The git operations it delegates to live in platforms/: cloning in git_client, plumbing in
git_gateway. This module is orchestration only.
"""
from pipeline.acquisition.loader import RepositoryLoader

__all__ = ["RepositoryLoader"]