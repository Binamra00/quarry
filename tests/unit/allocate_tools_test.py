import pytest
import hashlib
from unittest.mock import patch, mock_open
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


def test_verify_checksum_invalid_format(dummy_file):
    """Verify returns False if hash is not 64 chars hex."""
    path, _ = dummy_file
    assert allocate_tools.verify_checksum(path, "short_hash") is False
    assert allocate_tools.verify_checksum(path, "Z" * 64) is False  # Not hex


def test_verify_checksum_race_condition(dummy_file):
    """Verify returns False if file is present but read fails (Race Condition)."""
    path, expected_hash = dummy_file

    # Simulate file exists check passes, but open raises FileNotFoundError
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert allocate_tools.verify_checksum(path, expected_hash) is False


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_aborts_on_security_risk(mock_zip, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test that download_and_extract aborts if verify_checksum returns False."""

    # Mock Config Path to avoid side effects
    mock_config.TOOLS_PATH = tmp_path

    # Setup Security Failure
    mock_verify.return_value = False

    # Execute
    result = allocate_tools.download_and_extract("http://fake.url", "tool_v1", "a" * 64)

    # Assertions
    assert result is False
    mock_retrieve.assert_called_once()
    mock_zip.assert_not_called()


@patch("pipeline.utils.allocate_tools.download_and_extract")
def test_provision_raises_error_on_failure(mock_download):
    """Test provision raises RuntimeError if any tool fails (PMD=False, RM=True)."""

    # Simulate PMD failing, RM succeeding
    mock_download.side_effect = [False, True]

    with pytest.raises(RuntimeError, match="Toolchain provisioning failed"):
        allocate_tools.provision()