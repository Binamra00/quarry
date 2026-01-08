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
    assert allocate_tools.verify_checksum(path, "short") is False
    assert allocate_tools.verify_checksum(path, expected_hash.upper()) is False


def test_verify_checksum_race_condition(dummy_file):
    path, expected_hash = dummy_file
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert allocate_tools.verify_checksum(path, expected_hash) is False


# --- DOWNLOAD & EXTRACT TESTS ---

@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_and_extract_success(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test the happy path where download, verification, and extraction succeed."""

    # 1. Setup Environment
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    # 2. Mock Zip Content
    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    # The zip contains a folder "extracted_root" which needs to be renamed to "target_tool"
    zip_root_name = "extracted_root"
    valid_member = zipfile.ZipInfo(filename=f"{zip_root_name}/file.txt")
    mock_zip_instance.infolist.return_value = [valid_member]

    # 3. Simulate Extraction Side Effect
    # We must actually create the folder in tmp_path so the logic sees it exists
    def simulate_extraction(*args, **kwargs):
        (tmp_path / zip_root_name).mkdir()

    mock_zip_instance.extractall.side_effect = simulate_extraction

    # 4. Execute
    target_name = "target_tool"
    result = allocate_tools.download_and_extract("http://url", target_name, "hash")

    # 5. Assertions
    assert result is True
    # Verify the rename logic worked ("extracted_root" -> "target_tool")
    assert (tmp_path / target_name).exists()
    assert not (tmp_path / zip_root_name).exists()
    mock_zip_instance.extractall.assert_called_once()


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_zip_slip_prevention(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    malicious_member = zipfile.ZipInfo(filename="../etc/passwd")
    mock_zip_instance.infolist.return_value = [malicious_member]

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False
    mock_zip_instance.extractall.assert_not_called()


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_empty_zip_failure(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    # Simulate Empty Zip
    mock_zip_instance.infolist.return_value = []

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False
    mock_zip_instance.extractall.assert_not_called()


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.zipfile.ZipFile")
def test_download_missing_extracted_folder(mock_zip_cls, mock_verify, mock_retrieve, mock_config, tmp_path):
    """Test scenario where extraction succeeds but the root folder is gone."""
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = True

    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    valid_member = zipfile.ZipInfo(filename="root/file.txt")
    mock_zip_instance.infolist.return_value = [valid_member]

    # We do NOT create the directory, simulating a phantom extraction

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False


@patch("pipeline.utils.allocate_tools.config")
@patch("pipeline.utils.allocate_tools.urllib.request.urlretrieve")
@patch("pipeline.utils.allocate_tools.verify_checksum")
@patch("pipeline.utils.allocate_tools.Path.unlink")
def test_download_security_cleanup(mock_unlink, mock_verify, mock_retrieve, mock_config, tmp_path):
    mock_config.TOOLS_PATH = tmp_path
    mock_verify.return_value = False

    result = allocate_tools.download_and_extract("http://url", "target", "hash")

    assert result is False
    mock_unlink.assert_called_with(missing_ok=True)


# --- PROVISION TESTS ---

@patch("pipeline.utils.allocate_tools.make_executable")
@patch("pipeline.utils.allocate_tools.download_and_extract")
def test_provision_scenarios(mock_download, mock_make_exec):
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
    try:
        allocate_tools.provision()
    except RuntimeError:
        pytest.fail("Provision raised RuntimeError on success path")

    assert mock_make_exec.call_count == 2