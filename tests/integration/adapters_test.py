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
        # --- CRITICAL FIX: Configure State Manager Mock ---
        # Ensure the loop runs by telling the state manager this commit isn't done yet
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False
        # --------------------------------------------------

        # Setup
        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        # Mock internal helpers to isolate the execute loop
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        # Mock sequence of run_command calls:
        # 1. git symbolic-ref (get branch) -> Success
        # 2. git checkout (time travel) -> Success
        # 3. PMD Execution -> Success (We only care about the ARGS passed here)
        # 4. git checkout (restore) -> Success
        mock_run_command.side_effect = [
            (True, "main"),  # 1. Get Branch
            (True, ""),  # 2. Checkout Commit
            (True, ""),  # 3. PMD Run
            (True, "")  # 4. Restore Branch
        ]

        # Action
        # We need to mock open() because execute() writes logs
        with patch("builtins.open", mock_open()):
            adapter.execute()

        # Assert: Find the PMD call and check its arguments
        pmd_call_found = False
        for call_args in mock_run_command.call_args_list:
            args, kwargs = call_args
            cmd_list = args[0]
            # Identify the PMD command by looking for the binary path or 'check' arg
            if cmd_list and "check" in cmd_list:
                # CRITICAL CHECK: Did we allow exit code 4?
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
        # --- CRITICAL FIX: Configure State Manager Mock ---
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False
        # --------------------------------------------------

        # Setup
        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        # Mock sequence: PMD FAILS with TIMEOUT string
        mock_run_command.side_effect = [
            (True, "main"),  # Branch
            (True, ""),  # Checkout
            (False, "TIMEOUT"),  # PMD FAILS
            (True, "")  # Restore
        ]

        # Action & Assert
        # We assume the adapter writes to the JSONL file. We capture that write.
        with patch("builtins.open", mock_open()) as mock_file:
            adapter.execute()

            # Inspect writes to find the JSONL record
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
        # --- CRITICAL FIX: Configure State Manager Mock ---
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False
        # --------------------------------------------------

        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        # Mock sequence: Crash during PMD execution
        mock_run_command.side_effect = [
            (True, "main"),
            (True, ""),
            RuntimeError("Simulated Crash"),  # CRASH!
            (True, "")  # The Restore call (Should still happen)
        ]

        # Action
        with pytest.raises(RuntimeError):
            with patch("builtins.open", mock_open()):
                adapter.execute()

        # Assert: Verify the LAST call to run_command was restoring main
        last_call = mock_run_command.call_args
        cmd_arg = last_call[0][0]
        # We expect: ['git', 'checkout', '-f', 'main']
        assert cmd_arg[0] == "git" and cmd_arg[1] == "checkout", "Must attempt git checkout in finally block"
        assert cmd_arg[3] == "main", "Must restore to the captured branch (main)"


class TestRefmAdapterIntegration:

    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_all_commits")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._load_existing_results")
    def test_smart_skipping_logic(self, mock_load, mock_get_commits):
        """
        Test 4: Resume Capability.
        If output matches input list, execute() should return True immediately
        """
        # Setup
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_get_commits.return_value = ["sha1", "sha2"]
        # Simulate all commits already processed
        mock_load.return_value = [{"sha1": "sha1"}, {"sha1": "sha2"}]

        # Action
        # Mock subprocess to ensure it is NOT called
        with patch("subprocess.run") as mock_subprocess:
            result = adapter.execute()

            # Assert
            assert result is True
            mock_subprocess.assert_not_called()