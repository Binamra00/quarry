import pytest
import hashlib
import zipfile
from unittest.mock import patch, MagicMock
from pipeline.utils import allocate_tools


# --- FIXTURES ---

@pytest.fixture
def dummy_file(tmp_path):
    p = tmp_path / "test_file.txt"
    content = b"test_content"
    p.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    return p, sha


# --- CHECKSUM TESTS ---

def test_verify_checksum_success(dummy_file):
    path, expected_hash = dummy_file
    assert allocate_tools.verify_checksum(path, expected_hash) is True


def test_verify_checksum_mismatch(dummy_file):
    path, _ = dummy_file
    wrong_hash = "a" * 64
    assert allocate_tools.verify_checksum(path, wrong_hash) is False


def test_verify_checksum_invalid_format(dummy_file):
    path, expected_hash = dummy_file
    # Too short
    assert allocate_tools.verify_checksum(path, "short") is False
    # Uppercase (Should fail strict lowercase check)
    assert allocate_tools.verify_checksum(path, expected_hash.upper()) is False


def test_verify_checksum_race_condition(dummy_file):
    """Verify returns False if file exists check passes but open fails."""
    path, expected_hash = dummy_file
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert allocate_tools.verify_checksum(path, expected_hash) is False


# --- DOWNLOAD & EXTRACT TESTS ---

@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_zip_slip_prevention(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test that we reject zips containing '..' traversal attempts."""

    # Setup
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    # Mock a ZipFile that contains a malicious path
    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    malicious_member = zipfile.ZipInfo(filename="../etc/passwd")
    valid_member = zipfile.ZipInfo(filename="root/safe.txt")

    # infolist() returns the list of members
    mock_zip_instance.infolist.return_value = [valid_member, malicious_member]

    # Execute
    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    # Assert
    assert result is False
    # Ensure extraction was NOT called
    mock_zip_instance.extractall.assert_not_called()


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_multiple_roots_failure(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test that we reject zips with multiple top-level folders."""
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    # Two different roots
    m1 = zipfile.ZipInfo(filename="FolderA/file.txt")
    m2 = zipfile.ZipInfo(filename="FolderB/file.txt")
    mock_zip_instance.infolist.return_value = [m1, m2]

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.Path.unlink")  # Mock unlink to verify cleanup
def test_download_security_cleanup(mock_unlink, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test that compromised files are deleted."""
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = False  # Security Fail

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False
    mock_unlink.assert_called_with(missing_ok=True)


# --- PROVISION TESTS ---

@patch("pipeline.utils.allocate_tools.download_and_extract")
def test_provision_scenarios(mock_download):
    """Test the matrix of success/failure for provisioning."""

    # Case 1: PMD Fails
    mock_download.side_effect = [False, True]
    with pytest.raises(RuntimeError):
        allocate_tools.provision()

    # Case 2: RM Fails
    mock_download.side_effect = [True, False]
    with pytest.raises(RuntimeError):
        allocate_tools.provision()

    # Case 3: Both Fail
    mock_download.side_effect = [False, False]
    with pytest.raises(RuntimeError):
        allocate_tools.provision()

    # Case 4: Success
    mock_download.side_effect = [True, True]
    # Should not raise
    try:
        allocate_tools.provision()
    except RuntimeError:
        pytest.fail("Provision raised RuntimeError on success path")