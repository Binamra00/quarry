import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from pipeline.adapters.pmd_history_adapt import PMDHistoryAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter


# ==========================================
# TEST SUITE: INTEGRATION (MOCKED)
# Goal: Verify tool orchestration without running actual binaries.
# ==========================================

class TestPMDAdapterIntegration:
    """Verifies PMD execution logic and error handling."""

    @patch("pipeline.adapters.pmd_history_adapt.BatchStateManager")
    @patch("pipeline.utils.adapter_subprocess.run_command")
    def test_pmd_configuration_allows_exit_code_4(self, mock_run_command, mock_state_manager):
        """
        Test 1: Verify that PMD execution is configured to accept Exit Code 4.
        """
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False

        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        mock_run_command.side_effect = [
            (True, "main"),  # 1. Get Branch
            (True, ""),  # 2. Checkout Commit
            (True, ""),  # 3. PMD Run
            (True, "")  # 4. Restore Branch
        ]

        with patch("builtins.open", mock_open()):
            adapter.execute()

        pmd_call_found = False
        for call_args in mock_run_command.call_args_list:
            args, kwargs = call_args
            cmd_list = args[0]
            if cmd_list and "check" in cmd_list:
                if kwargs.get("allowed_exit_codes") == [0, 4]:
                    pmd_call_found = True
                    break

        assert pmd_call_found, "PMD command must be called with allowed_exit_codes=[0, 4]"

    @patch("pipeline.adapters.pmd_history_adapt.BatchStateManager")
    @patch("pipeline.utils.adapter_subprocess.run_command")
    def test_pmd_timeout_recording(self, mock_run_command, mock_state_manager):
        """
        Test 2: The Poison Pill Simulation.
        If PMD times out, the adapter should record "status": "timeout" in JSONL.
        """
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False

        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        mock_run_command.side_effect = [
            (True, "main"),
            (True, ""),
            (False, "TIMEOUT"),  # PMD FAILS
            (True, "")
        ]

        with patch("builtins.open", mock_open()) as mock_file:
            adapter.execute()

            handle = mock_file()
            found_timeout_record = False
            for name, args, kwargs in handle.write.mock_calls:
                written_str = args[0]
                if '"status": "timeout"' in written_str:
                    found_timeout_record = True
                    break

            assert found_timeout_record, "Adapter should write 'timeout' status to JSONL log on failure"

    @patch("pipeline.adapters.pmd_history_adapt.BatchStateManager")
    @patch("pipeline.utils.adapter_subprocess.run_command")
    def test_git_checkout_safety(self, mock_run_command, mock_state_manager):
        """
        Test 3: Time-Travel Safety.
        Verify that we ALWAYS checkout main after processing, even if code crashes.
        """
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False

        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        mock_run_command.side_effect = [
            (True, "main"),
            (True, ""),
            RuntimeError("Simulated Crash"),
            (True, "")
        ]

        with pytest.raises(RuntimeError):
            with patch("builtins.open", mock_open()):
                adapter.execute()

        last_call = mock_run_command.call_args
        cmd_arg = last_call[0][0]
        assert cmd_arg[0] == "git" and cmd_arg[1] == "checkout", "Must attempt git checkout in finally block"
        assert cmd_arg[3] == "main", "Must restore to the captured branch (main)"


class TestRefmAdapterIntegration:

    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_all_commits")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_processed_shas")  # [FIX] Updated method name
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_smart_skipping_logic(self, mock_lib_path, mock_get_shas, mock_get_commits):
        """
        Test 4: Resume Capability.
        If processed SHAs match input list, execute() should return True immediately.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_lib_path.return_value = Path("fake/lib/path")

        # Input: 2 Commits
        mock_get_commits.return_value = ["sha1", "sha2"]

        # [FIX] State: Both commits are already in the set
        mock_get_shas.return_value = {"sha1", "sha2"}

        with patch("subprocess.run") as mock_subprocess:
            result = adapter.execute()

            assert result is True
            mock_subprocess.assert_not_called()