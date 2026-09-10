"""
Everything that must be true before a miner can run.

This is the part of the old main() that had no decisions in it: a fixed sequence of
provision -> acquire -> sync -> pin, where each step's only branch was "did it fail". It sat in
main because it had nowhere else to be.

WHY SYNC IS NOT `git fetch` FOLLOWED BY `git checkout`

    The version this replaced ran `git fetch --all --tags` and then `git checkout -f <branch>`,
    which looks correct and is not: fetch moves refs/remotes/origin/*, never refs/heads/*, so
    the checkout landed on a LOCAL branch that could be months behind. The objects were all
    present, HEAD simply pointed into the past, and every adapter walking HEAD mined a
    truncated history without raising anything. RepositoryLoader.sync_to_remote fast-forwards
    the local branch onto origin instead.
"""

from pathlib import Path

from pipeline.utils import adapter_subprocess
from pipeline.utils import allocate_tools
from pipeline.acquisition import RepositoryLoader
from pipeline.cli.plan import RunPlan


class WorkspaceError(RuntimeError):
    """The workspace could not be brought into a state where mining is possible."""


class Workspace:

    @staticmethod
    def prepare(plan: RunPlan) -> Path:
        """
        Provision the toolchain, obtain the repository, and pin it to the requested revision.

        Returns the local repository path. Raises WorkspaceError with a message meant for the
        user; nothing here calls sys.exit, so the sequence stays usable outside a terminal.
        """
        Workspace._provision()
        repo = Workspace._acquire(plan)
        Workspace._sync(repo, plan)
        Workspace._trace_revision(repo, plan)
        return repo

    # ------------------------------------------------------------------ steps

    @staticmethod
    def _provision() -> None:
        print("\n--- 🛠️ Verifying Toolchain ---")
        try:
            allocate_tools.provision()
        except (RuntimeError, OSError) as e:
            # Narrow on purpose: a missing download or an unwritable tools directory is a setup
            # problem worth a readable message. Anything else is a bug and should surface as a
            # traceback rather than be flattened into "provisioning failed".
            raise WorkspaceError(f"Tool provisioning failed. Cannot proceed.\n   Error: {e}")

    @staticmethod
    def _acquire(plan: RunPlan) -> Path:
        try:
            repo = RepositoryLoader.ensure_local_copy(plan.repo, plan.version)
        except FileNotFoundError as e:
            # A user error: the folder is not there, or the URL is wrong.
            raise WorkspaceError(f"REPOSITORY ERROR:\n   {e}")
        except (ValueError, RuntimeError) as e:
            # A system error: a rejected URL, a failed clone.
            raise WorkspaceError(f"CRITICAL ERROR:\n   {e}")
        print(f"🎯 Target Repository: {repo.name}")
        return repo

    @staticmethod
    def _sync(repo: Path, plan: RunPlan) -> None:
        print("\n--- Step 1: Repository Verification ---")
        RepositoryLoader.sync_to_remote(repo, pinned_version=plan.version)
        if plan.version:
            # Force the workspace to match the study target exactly.
            adapter_subprocess.run_command(
                ["git", "checkout", "-f", plan.version], cwd=str(repo))

    @staticmethod
    def _trace_revision(repo: Path, plan: RunPlan) -> None:
        """Record which revision was actually mined. Only meaningful for a pinned run."""
        if not plan.version:
            return
        print("\n--- 🔖 Repo Revision (Trace) ---")
        adapter_subprocess.run_command(["git", "describe", "--tags", "--always"], cwd=str(repo))
        adapter_subprocess.run_command(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo))
