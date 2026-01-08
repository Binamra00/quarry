import pytest
import hashlib
from unittest.mock import patch, MagicMock
from pathlib import Path
from pipeline.utils import allocate_tools


# Fixture to create a dummy file with known hash
@pytest.fixture
def dummy_file(tmp_path):
    p = tmp_path / "test_file.txt"
    content = b"test_content"
    p.write_bytes(content)
    # Calculate expected hash
    sha = hashlib.sha256(content).hexdigest()
    return p, sha


def test_verify_checksum_success(dummy_file):
    """Verify returns True for matching hash."""
    path, expected_hash = dummy_file
    assert allocate_tools.verify_checksum(path, expected_hash) is True


def test_verify_checksum_mismatch(dummy_file):
    """Verify returns False for mismatched hash."""
    path, _ = dummy_file
    wrong_hash = "a" * 64
    assert allocate_tools.verify_checksum(path, wrong_hash) is False


def test_verify_checksum_missing_file(tmp_path):
    """Verify handles missing files gracefully."""
    missing = tmp_path / "non_existent.txt"
    assert allocate_tools.verify_checksum(missing, "any_hash") is False


@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_aborts_on_security_risk(mock_zip, mock_verify, mock_retrieve, tmp_path):
    """Test that download_and_extract aborts if verify_checksum returns False."""

    # Setup Mocks
    mock_verify.return_value = False  # Simulate Security Failure
    target_dir = tmp_path / "target"

    # Execute
    result = allocate_tools.download_and_extract("http://fake.url", "tool_v1", "expected_hash")

    # Assertions
    assert result is False
    mock_retrieve.assert_called_once()  # It tried to download
    mock_zip.assert_not_called()  # But it never extracted!


@patch("pipeline.utils.allocate_tools.download_and_extract")
def test_provision_raises_error_on_failure(mock_download):
    """Test that provision raises RuntimeError if any tool fails."""

    # Simulate PMD failing
    mock_download.side_effect = [False, True]

    with pytest.raises(RuntimeError, match="Toolchain provisioning failed"):
        allocate_tools.provision()