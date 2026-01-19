import pytest
from unittest.mock import patch
from pipeline.utils.batch_state import BatchStateManager
from pipeline import config


class TestBatchStateManager:

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """
        Redirects config.OUTPUTS_PATH to a temporary pytest folder.
        This ensures every test starts with a clean slate.
        """
        self.mock_path = tmp_path
        # This patch forces the code to look at tmp_path instead of your real workspace
        with patch("pipeline.config.OUTPUTS_PATH", self.mock_path):
            yield

    def test_initialization_fresh(self):
        """Test 1: Should create default state if no file exists."""
        manager = BatchStateManager("test_repo", "pmd")

        assert manager.state["last_index"] == -1
        assert manager.state["is_complete"] is False
        assert len(manager.processed_set) == 0

    def test_state_persistence_reload(self):
        """Test 2: Should correctly load an existing state file."""
        # Setup: Create a fake state file
        repo = "persist_repo"
        tool = "pmd"
        manager = BatchStateManager(repo, tool)

        # Action: Simulate processing commit #0
        manager.save_progress(commit_hash="abc1234", index=0, total=10, flush=True)

        # Re-initialize (Simulate restart)
        new_manager = BatchStateManager(repo, tool)

        # Assert: State is preserved
        assert new_manager.state["last_index"] == 0
        assert "abc1234" in new_manager.processed_set
        assert new_manager.get_next_start_index() == 1

    def test_boundary_completion(self):
        """Test 3: BVA - is_complete should ONLY trigger at total - 1."""
        manager = BatchStateManager("bva_repo", "pmd")
        total_commits = 5

        # Case A: Process commit 3 (Index 3) -> Not Complete
        manager.save_progress("hash_3", index=3, total=total_commits, flush=False)
        assert manager.state["is_complete"] is False

        # Case B: Process commit 4 (Index 4) -> Complete (Boundary Hit)
        manager.save_progress("hash_4", index=4, total=total_commits, flush=False)
        assert manager.state["is_complete"] is True

    def test_corruption_resilience(self):
        """Test 4: Should archive corrupt JSON and reset state (Self-Healing)."""
        repo = "corrupt_repo"
        tool = "pmd"

        # [UPDATE]: Write to the temporary mock path, not the real config path
        state_file = self.mock_path / f"batch_status_{tool}_{repo}.json"
        state_file.write_text("{ incomplete_json: ...")  # Malformed

        # Action: Initialize manager (it reads from the mocked config.OUTPUTS_PATH)
        manager = BatchStateManager(repo, tool)

        # Assert:
        # 1. Manager should be alive (not crashed)
        assert manager.state["last_index"] == -1

        # 2. Corrupt file should be renamed (Archived)
        # [UPDATE]: Check the temporary folder
        archived_files = list(self.mock_path.glob("*.corrupt_*.json"))

        # Now this will always be 1, because the folder is fresh for every test run
        assert len(archived_files) == 1
        assert "batch_status_pmd_corrupt_repo" in archived_files[0].name

    def test_idempotency_no_duplicates(self):
        """Test 5: Processing the same SHA twice should not duplicate data."""
        manager = BatchStateManager("dedup_repo", "pmd")

        manager.save_progress("hash_X", 1, 10)
        manager.save_progress("hash_X", 1, 10)  # Duplicate

        assert len(manager.state["processed_shas"]) == 1
        assert len(manager.processed_set) == 1

    def test_atomic_flush_failure(self, mocker):
        """Test 6: Should handle OS permission errors gracefully."""
        manager = BatchStateManager("io_fail_repo", "pmd")

        # Mock os.replace to raise PermissionError
        mocker.patch("os.replace", side_effect=PermissionError("Locked"))

        # Action: Try to flush
        success = manager.flush()

        # Assert: Should return False, not crash
        assert success is False