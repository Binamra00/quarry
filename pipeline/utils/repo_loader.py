import re
import os
from pathlib import Path
from urllib.parse import urlparse
from pipeline import config
from pipeline.utils import adapter_subprocess


class RepositoryLoader:
    """
    Facade for Repository Acquisition.
    Responsible for resolving a '--repo' argument (URL or Name) into a valid local Path.
    Implements 'Lazy Loading' (Clones only if necessary) and Input Sanitization.
    """

    # Regex for standard Git URLs to prevent flag injection
    # Allows: https://, http://, git@, ssh://
    GIT_URL_PATTERN = re.compile(r"^(https?://|git@|ssh://).+")

    @staticmethod
    def ensure_local_copy(repo_argument: str) -> Path:
        """
        Ensures the repository exists in the workspace.

        Args:
            repo_argument (str): Either a Git URL or a local folder name.

        Returns:
            Path: The absolute path to the local repository.
        """
        # 1. Strategy: Is it a URL?
        if RepositoryLoader._is_git_url(repo_argument):
            return RepositoryLoader._handle_remote_clone(repo_argument)

        # 2. Strategy: Is it a local folder name?
        return RepositoryLoader._handle_local_lookup(repo_argument)

    @staticmethod
    def _is_git_url(s: str) -> bool:
        """
        Detects if the string looks like a Git URL.
        Validates against a regex to prevent Argument Injection (e.g., strings starting with '-').
        """
        # Security: Reject inputs starting with '-' to prevent flag injection
        if s.startswith("-"):
            raise ValueError(f"❌ Security Violation: Repository argument cannot start with '-': {s}")

        return bool(RepositoryLoader.GIT_URL_PATTERN.match(s))

    @staticmethod
    def _extract_name_from_url(url: str) -> str:
        """
        Extracts the repository name from a Git URL.
        Handles both HTTPS (https://github.com/user/repo.git) and SSH (git@github.com:user/repo.git).

        Security:
            - Sanitizes the output to contain only alphanumeric characters, underscores, and hyphens.
            - Raises ValueError if a safe name cannot be derived.
        """
        path = ""

        # Handle SSH-style URLs (git@host:path)
        ssh_match = re.match(r"^[^@]+@[^:]+:(.+)$", url)
        if ssh_match:
            path = ssh_match.group(1).strip("/")
        else:
            # Handle Standard URLs
            parsed = urlparse(url)
            path = parsed.path.strip("/")

        name = path.split("/")[-1] if path else ""
        if name.endswith(".git"):
            name = name[:-4]

        # Security: Ensure extracted name is safe for filesystem
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
        if not safe_name:
            raise ValueError(f"❌ Could not derive a safe folder name from URL: {url}")

        return safe_name

    @staticmethod
    def _handle_remote_clone(url: str) -> Path:
        repo_name = RepositoryLoader._extract_name_from_url(url)
        target_path = config.REPOS_PATH / repo_name

        # Idempotency Check: Don't clone if it exists
        # Note: Potential race condition if multiple processes start simultaneously.
        # For this single-user tool, we accept the risk.
        if target_path.exists():
            print(f"   🔍 Repo '{repo_name}' found locally. Skipping clone.")
            return target_path

        print(f"   ☁️  Cloning remote repository: {url}")
        print(f"       Destination: {target_path.name}")

        # Security: Use '--' to separate flags from positional arguments
        cmd = ["git", "clone", "--", url, str(target_path)]

        success, output = adapter_subprocess.run_command(cmd, verbose=True)

        if not success:
            raise RuntimeError(f"❌ Failed to clone repository: {url}\nGit Output: {output}")

        print(f"   ✅ Clone successful.")
        return target_path

    @staticmethod
    def _handle_local_lookup(folder_name: str) -> Path:
        """
        Resolves a local folder name to a Path, preventing path traversal.
        """
        target_path = config.REPOS_PATH / folder_name

        # Security: Sandbox Check (Path Traversal Protection)
        # We resolve the absolute path and ensure it is strictly inside REPOS_PATH
        try:
            base_path = config.REPOS_PATH.resolve()
            resolved_target = target_path.resolve()

            # This throws ValueError if resolved_target is not inside base_path
            if not resolved_target.is_relative_to(base_path):
                raise ValueError

        except (ValueError, RuntimeError):
            raise ValueError(f"❌ Security Violation: Path traversal detected in '{folder_name}'.")

        if not target_path.exists():
            raise FileNotFoundError(
                f"❌ Repository not found locally: {target_path}\n"
                f"   Tip: Double-check the folder name or pass a full Git URL (https://...)."
            )

        return target_path