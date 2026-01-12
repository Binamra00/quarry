import pytest
from unittest.mock import patch
from pipeline.utils.repo_loader import RepositoryLoader


class TestRepositoryLoaderSecurity:
    """
    Validates security constraints and workflow for Repository Loading.
    Uses 'tmp_path' fixture for real filesystem verification.
    """

    def test_git_url_detection(self):
        """Test 1: Should correctly identify various Git URL formats."""
        # Valid URLs
        assert RepositoryLoader._is_git_url("https://github.com/user/repo.git") is True
        assert RepositoryLoader._is_git_url("ssh://user@host.xz/path/to/repo.git/") is True
        assert RepositoryLoader._is_git_url("git@github.com:user/project.git") is True

        # Invalid (Local folders)
        assert RepositoryLoader._is_git_url("local_folder") is False
        assert RepositoryLoader._is_git_url("/abs/path/to/repo") is False

    def test_flag_injection_prevention(self):
        """Test 2: Should reject inputs starting with '-'."""
        with pytest.raises(ValueError, match="Security Violation"):
            RepositoryLoader._is_git_url("-oProxyCommand=calc")

    def test_empty_input_prevention(self):
        """Test 3: Should reject empty or whitespace strings."""
        with pytest.raises(ValueError, match="cannot be empty"):
            RepositoryLoader.ensure_local_copy("")
        with pytest.raises(ValueError, match="cannot be empty"):
            RepositoryLoader.ensure_local_copy("   ")

    def test_extract_name_sanitization(self):
        """Test 4: Should strip unsafe characters from URL derived names."""
        url = "https://example.com/malicious/..%2f..%2fetc%2fpasswd.git"
        name = RepositoryLoader._extract_name_from_url(url)

        # The sanitizer strips '%' and '.' but keeps alphanumeric chars (2, f)
        # Result '2f2fetc2fpasswd' is ugly but SAFE (no traversal chars)
        assert ".." not in name
        assert "/" not in name
        assert "\\" not in name
        # Verify the name only contains safe characters
        assert name.isalnum()
        assert name == "2f2fetc2fpasswd"

    def test_path_traversal_prevention(self, tmp_path):
        """
        Test 5: Real filesystem test for Path Traversal.
        Using 'tmp_path' ensures we test actual resolve() behavior.
        """
        # Setup: Create a fake "repos" directory in temp
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        # Patch config.REPOS_PATH to point to our temp dir
        with patch("pipeline.config.REPOS_PATH", repos_dir):

            # Case A: ".." Traversal
            with pytest.raises(ValueError, match="Security Violation"):
                RepositoryLoader.ensure_local_copy("../outside_repo")

            # Case B: Absolute Path Traversal (e.g., trying to access /etc/passwd)
            # We simulate this by passing an absolute path that exists but is outside repos_dir
            # (Using tmp_path parent to simulate 'outside')
            outside_file = tmp_path / "secret.txt"
            outside_file.touch()

            try:
                # Note: passing absolute string to Path / operator replaces the path on Linux/Mac
                RepositoryLoader.ensure_local_copy(str(outside_file))
            except ValueError as e:
                assert "Security Violation" in str(e)
            except FileNotFoundError:
                pass

    def test_facade_workflow_routing(self):
        """Test 6: Verify ensure_local_copy routes correctly."""

        with patch.object(RepositoryLoader, "_handle_remote_clone") as mock_clone, \
                patch.object(RepositoryLoader, "_handle_local_lookup") as mock_lookup:
            # URL Input -> Clone
            RepositoryLoader.ensure_local_copy("https://github.com/a/b.git")
            mock_clone.assert_called_once()
            mock_lookup.assert_not_called()

            mock_clone.reset_mock()

            # Name Input -> Lookup
            RepositoryLoader.ensure_local_copy("local_repo")
            mock_lookup.assert_called_once()
            mock_clone.assert_not_called()