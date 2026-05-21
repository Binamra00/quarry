import re
from pathlib import Path
from urllib.parse import urlparse
from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils.git_manager import GitManager


class RepositoryLoader:
    """
    Facade for Repository Acquisition.
    Responsible for resolving a '--repo' argument (URL or Name) into a valid local Path.
    Implements 'Lazy Loading' (Clones only if necessary) and Input Sanitization.
    """

    # Enforces a minimal structure:
    #   - http(s)://host[/optional-path]
    #   - ssh://host[/optional-path]
    #   - git@host:path
    GIT_URL_PATTERN = re.compile(
        r"^(?:"
        r"https?://[^/\s]+(?:/[^ \t\r\n]*)?"
        r"|ssh://[^/\s]+(?:/[^ \t\r\n]*)?"
        r"|git@[^:\s]+:[^ \t\r\n]+"
        r")$"
    )

    @staticmethod
    def ensure_local_copy(repo_argument: str, version: str = None) -> Path:
        """
        Ensures the repository exists in the workspace and is on the correct version.

        Args:
            repo_argument (str): Either a Git URL or a local folder name.
            version (str, optional): A Git Tag or Commit Hash to checkout.

        Returns:
            Path: The absolute path to the local repository.
        """
        if not repo_argument or not repo_argument.strip():
            raise ValueError("❌ Repository argument cannot be empty.")

        # 1. Strategy: Resolve Path (Remote Clone or Local Lookup)
        if RepositoryLoader._is_git_url(repo_argument):
            target_path = RepositoryLoader._handle_remote_clone(repo_argument)
        else:
            target_path = RepositoryLoader._handle_local_lookup(repo_argument)

        # 2. Version Management: Checkout specific tag/commit if requested
        if version:
            RepositoryLoader._checkout_version(target_path, version)

        return target_path

    @staticmethod
    def _checkout_version(target_path: Path, version: str):
        """
        Forces the repository to a specific version (Tag, Branch, or Commit).
        """
        print(f"   🔄 Pinning repository to version: {version}...")

        # 1. Fetch tags to ensure we see 'jena-3.1.0'
        adapter_subprocess.run_command(["git", "-C", str(target_path), "fetch", "--tags"])

        # 2. Force checkout the target version
        checkout_cmd = ["git", "-C", str(target_path), "checkout", "-f", version]
        success, output = adapter_subprocess.run_command(checkout_cmd, verbose=True)

        if not success:
            raise RuntimeError(f"❌ Failed to checkout version '{version}':\n{output}")

        print(f"   ✅ Successfully checked out {version}")

    @staticmethod
    def _is_git_url(s: str) -> bool:
        """
        Detects if the string looks like a Git URL.

        Raises:
             ValueError: If input starts with '-' (Argument Injection protection).
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
        if target_path.exists():
            print(f"   🔍 Repo '{repo_name}' found locally. Skipping clone.")
            return target_path

        # Let the GitManager handle the clone and stream the live progress bar
        success = GitManager.clone_with_progress(url, target_path)

        if not success:
            raise RuntimeError(f"❌ Failed to clone repository: {url}")

        return target_path

    @staticmethod
    def _handle_local_lookup(folder_name: str) -> Path:
        """
        Resolves a local folder name to a Path, preventing path traversal.
        """
        target_path = config.REPOS_PATH / folder_name

        # Security: Sandbox Check (Path Traversal Protection)
        try:
            base_path = config.REPOS_PATH.resolve()
            resolved_target = target_path.resolve()

            # Use strict relative_to check to ensure we stay inside the sandbox
            if not resolved_target.is_relative_to(base_path):
                raise ValueError("Traversing outside sandbox")

        except (ValueError, RuntimeError):
            raise ValueError(f"❌ Security Violation: Path traversal detected in '{folder_name}'.")

        if not target_path.exists():
            raise FileNotFoundError(
                f"❌ Repository not found locally: {target_path}\n"
                f"   Tip: Double-check the folder name or pass a full Git URL (https://...)."
            )

        return target_path