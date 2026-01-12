import pytest
import json
from unittest.mock import patch
from pathlib import Path
from pipeline.adapters.metadata_adapt import MetadataAdapter
from pipeline.config import OUTPUTS_PATH


@pytest.fixture
def mock_repo_path():
    return Path("dummy_repo")


def test_lineage_extraction_success(mock_repo_path, tmp_path):
    """Verify git log output is correctly parsed into JSONL."""

    # Mock Git Log Output: "Hash ParentHash"
    # c1 has parent p1
    # p1 has parent p0
    git_output = "c1 p1\np1 p0\np0 "

    adapter = MetadataAdapter(mock_repo_path)

    # Patch subprocess to return our fake log
    with patch("subprocess.run") as mock_run, \
            patch("pipeline.adapters.metadata_adapt.config.OUTPUTS_PATH", tmp_path):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = git_output

        assert adapter.execute() is True

        # Verify Output File Content
        output_file = tmp_path / f"commit_lineage_{mock_repo_path.name}.jsonl"
        assert output_file.exists()

        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 3

        # Check first record
        rec1 = json.loads(lines[0])
        assert rec1["commit_sha"] == "c1"
        assert rec1["parent_sha"] == "p1"


def test_merge_commit_handling(mock_repo_path, tmp_path):
    """Verify merge commits (2 parents) only take the first parent."""

    # c_merge has parents p1 and p2. Logic should pick p1.
    git_output = "c_merge p1 p2"

    adapter = MetadataAdapter(mock_repo_path)

    with patch("subprocess.run") as mock_run, \
            patch("pipeline.adapters.metadata_adapt.config.OUTPUTS_PATH", tmp_path):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = git_output

        adapter.execute()

        output_file = tmp_path / f"commit_lineage_{mock_repo_path.name}.jsonl"
        data = json.loads(output_file.read_text().strip())

        assert data["commit_sha"] == "c_merge"
        assert data["parent_sha"] == "p1"  # Strict First-Parent check


def test_git_command_failure(mock_repo_path):
    """Verify adapter handles git crashes gracefully."""

    adapter = MetadataAdapter(mock_repo_path)

    with patch("subprocess.run") as mock_run:
        # Simulate Git crash (non-zero exit code)
        mock_run.return_value.returncode = 128
        mock_run.return_value.stderr = "fatal: not a git repository"

        assert adapter.execute() is False


def test_tool_name_and_path(mock_repo_path):
    """Verify interface compliance."""
    adapter = MetadataAdapter(mock_repo_path)
    assert adapter.get_tool_name() == "Metadata Miner (Git Lineage)"
    expected_path = OUTPUTS_PATH / "commit_lineage_dummy_repo.jsonl"
    assert adapter.get_output_path() == expected_path