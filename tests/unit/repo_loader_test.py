import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.utils.repo_loader import RepositoryLoader
from pipeline import config


class TestRepositoryLoaderSecurity:
    """
    Validates security constraints for Repository Loading.
    Focuses on Input Sanitization and Path Traversal protection.
    """

    def test_git_url_detection(self):
        """Test 1: Should correctly identify various Git URL formats."""
        assert RepositoryLoader._is_git_url("https://github.com/user/repo.git") is True
        assert RepositoryLoader._is_git_url("ssh://user@host.xz/path/to/repo.git/") is True
        assert RepositoryLoader._is_git_url("git@github.com:user/project.git") is True
        assert RepositoryLoader._is_git_url("local_folder") is False

    def test_flag_injection_prevention(self):
        """Test 2: Should reject inputs starting with '-'."""
        with pytest.raises(ValueError, match="Security Violation"):
            RepositoryLoader._is_git_url("-oProxyCommand=calc")

    def test_extract_name_https(self):
        """Test 3: Extract name from standard HTTPS URL."""
        url = "https://github.com/apache/commons-lang.git"
        assert RepositoryLoader._extract_name_from_url(url) == "commons-lang"

    def test_extract_name_ssh(self):
        """Test 4: Extract name from SSH/SCP-like URL."""
        url = "git@github.com:apache/commons-text.git"
        assert RepositoryLoader._extract_name_from_url(url) == "commons-text"

    def test_extract_name_sanitization(self):
        """Test 5: Should strip unsafe characters."""
        url = "https://example.com/malicious/..%2f..%2fetc%2fpasswd.git"
        # The logic strips special chars, leaving only alphanumeric
        name = RepositoryLoader._extract_name_from_url(url)
        assert ".." not in name
        assert "/" not in name

    @patch("pathlib.Path.resolve")
    @patch("pathlib.Path.exists")
    def test_path_traversal_prevention(self, mock_exists, mock_resolve):
        """Test 6: Should block '..' attempts in local folder lookup."""
        # Setup mocks
        base_path = Path("/workspace/repos")
        # Attempt to escape sandbox
        malicious_path = Path("/workspace/repos/../../etc/passwd")

        # Configure resolve behavior
        def resolve_side_effect():
            # If we call resolve on the malicious path, it returns /etc/passwd
            if str(mock_resolve.call_args[0]) == str(malicious_path):
                return Path("/etc/passwd")
            return base_path

        # We need to mock config.REPOS_PATH.resolve() specifically
        # This is complex to mock perfectly without fs, so we rely on the logic test:
        # verifying checking for ValueError

        # Simpler approach: Verify the logic explicitly raises on traversal
        loader = RepositoryLoader()

        # We simulate the logic failure by creating a mismatch in relative_to
        with patch("pipeline.config.REPOS_PATH", base_path):
            # Mock the Resolved paths
            mock_resolve.side_effect = [base_path, Path("/etc/passwd")]

            with pytest.raises(ValueError, match="Security Violation"):
                RepositoryLoader._handle_local_lookup("../../etc/passwd")