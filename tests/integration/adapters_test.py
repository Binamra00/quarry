import pytest
import json
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

    @patch("pipeline.adapters.pmd_history_adapt.BatchStateManager")
    @patch("pipeline.utils.adapter_subprocess.run_command")
    @patch("pipeline.adapters.pmd_history_adapt.uuid")  # Patch UUID to predict temp filename
    def test_pmd_enrichment_logic(self, mock_uuid, mock_run_command, mock_state_manager):
        """
        Test 5: Enrichment Verification.
        Verifies that 'metric_value' is extracted from the temp file
        and correctly injected into the final JSONL output.
        """
        # 1. Setup Mocks
        instance_mock = mock_state_manager.return_value
        instance_mock.get_next_start_index.return_value = 0
        instance_mock.is_commit_processed.return_value = False

        # Force a predictable UUID so we can match the temp filename
        mock_uuid.uuid4.return_value.hex = "12345678"

        adapter = PMDHistoryAdapter(Path("dummy_repo"))
        adapter._get_total_commit_count = MagicMock(return_value=1)
        adapter._get_commit_batch = MagicMock(return_value=["sha1"])

        # Mock sequence of commands:
        # 1. Get Branch -> 2. Checkout -> 3. Run PMD -> 4. Restore Branch
        mock_run_command.side_effect = [
            (True, "main"),
            (True, ""),
            (True, ""),
            (True, "")
        ]

        # 2. Mock File System I/O
        # The raw JSON that PMD 'writes' to the temp file
        raw_pmd_output = json.dumps({
            "files": [{
                "violations": [
                    {
                        "rule": "CyclomaticComplexity",
                        "message": "The method 'calculate' has a cyclomatic complexity of 15."
                    },
                    {
                        "rule": "NcssCount",
                        "message": "The method 'calculate' has an NCSS line count of 50."
                    }
                ]
            }]
        })

        # Handles for verifying writes/reads
        mock_jsonl_handle = MagicMock()
        mock_temp_handle = mock_open(read_data=raw_pmd_output).return_value

        def open_side_effect(filename, mode='r', **kwargs):
            fname = str(filename)
            # Intercept reading the temporary PMD file
            if "pmd_" in fname and ".json" in fname and "r" in mode:
                return mock_temp_handle
            # Intercept appending to the final JSONL log
            if ".jsonl" in fname and "a" in mode:
                m = MagicMock()
                m.__enter__.return_value = mock_jsonl_handle
                return m
            # Default for log files, etc.
            return MagicMock()

        # Apply patches
        with patch("builtins.open", side_effect=open_side_effect):
            # We must also patch Path.exists/stat to pass the file validation checks
            with patch("pathlib.Path.exists", return_value=True), \
                    patch("pathlib.Path.stat", MagicMock(return_value=MagicMock(st_size=100))):
                # EXECUTE
                adapter.execute()

        # 3. Assertions
        # Verify that we wrote to the JSONL file
        assert mock_jsonl_handle.write.called, "Adapter failed to write to JSONL output"

        # Capture what was written
        args, _ = mock_jsonl_handle.write.call_args
        written_json_str = args[0]
        written_record = json.loads(written_json_str)

        # Verify the enrichment
        violations = written_record['violations'][0]['violations']

        # Check CC injection
        assert violations[0]['metric_value'] == 15, "Failed to inject CC score of 15"
        # Check NCSS injection
        assert violations[1]['metric_value'] == 50, "Failed to inject NCSS score of 50"


class TestRefmAdapterIntegration:

    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_all_commits")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_processed_shas")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_smart_skipping_logic(self, mock_lib_path, mock_get_shas, mock_get_commits):
        """
        Test 4: Resume Capability.
        If processed SHAs match input list, execute() should return True immediately.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_lib_path.return_value = Path("fake/lib/path")
        mock_get_commits.return_value = ["sha1", "sha2"]
        mock_get_shas.return_value = {"sha1", "sha2"}

        with patch("subprocess.run") as mock_subprocess:
            result = adapter.execute()
            assert result is True
            mock_subprocess.assert_not_called()

    @patch("pipeline.utils.ui_strategy.update_progress")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_all_commits")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_processed_shas")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_refm_streaming_integrity(self, mock_lib, mock_shas, mock_commits, mock_ui):
        """
        Test 5: Streaming Integrity (Happy Path).
        Verify that the adapter writes valid JSONL records AND logs execution details.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_lib.return_value = Path("lib")
        mock_commits.return_value = ["sha_new"]
        mock_shas.return_value = set()
        tool_output_content = json.dumps({"refactorings": [{"type": "Extract Method"}]})

        mock_stream_handle = MagicMock()
        mock_log_handle = MagicMock()
        mock_temp_handle = mock_open(read_data=tool_output_content).return_value

        def open_side_effect(filename, mode='r', **kwargs):
            filename_str = str(filename)
            if "refactorings_" in filename_str and ".jsonl" in filename_str and mode == 'a':
                m = MagicMock()
                m.__enter__.return_value = mock_stream_handle
                return m
            elif ".log" in filename_str and mode == 'a':
                m = MagicMock()
                m.__enter__.return_value = mock_log_handle
                return m
            elif "rm_" in filename_str and mode == 'r':
                m = MagicMock()
                m.__enter__.return_value = mock_temp_handle
                return m
            return MagicMock()

        with patch("subprocess.run") as mock_sub, \
                patch("builtins.open", side_effect=open_side_effect) as mock_file, \
                patch("pathlib.Path.exists", return_value=True), \
                patch("pathlib.Path.stat", MagicMock(return_value=MagicMock(st_size=100))), \
                patch("pathlib.Path.mkdir"):

            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stderr = ""

            adapter.execute()

            stream_calls = mock_stream_handle.write.call_args_list
            assert any('sha_new' in args[0] for args, _ in stream_calls), "Stream must contain commit SHA"

            log_calls = mock_log_handle.write.call_args_list
            assert any('[DEBUG] Java Command' in args[0] for args, _ in log_calls), "Log must record debug command"

    @patch("pipeline.utils.ui_strategy.update_progress")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_all_commits")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_processed_shas")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_refm_tool_failure_handling(self, mock_lib, mock_shas, mock_commits, mock_ui):
        """
        Test 6: Failure Handling.
        Verify that a tool crash (exit code 1) is logged to the log file.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_lib.return_value = Path("lib")
        mock_commits.return_value = ["sha_fail"]
        mock_shas.return_value = set()

        mock_log_handle = MagicMock()
        mock_stream_handle = MagicMock()

        def open_side_effect(filename, mode='r', **kwargs):
            filename_str = str(filename)
            if "refactorings_" in filename_str and ".jsonl" in filename_str and mode == 'a':
                m = MagicMock()
                m.__enter__.return_value = mock_stream_handle
                return m
            elif ".log" in filename_str and mode == 'a':
                m = MagicMock()
                m.__enter__.return_value = mock_log_handle
                return m
            return MagicMock()

        with patch("subprocess.run") as mock_sub, \
                patch("builtins.open", side_effect=open_side_effect), \
                patch("pathlib.Path.exists", return_value=False), \
                patch("pathlib.Path.mkdir"):

            mock_sub.return_value.returncode = 1
            mock_sub.return_value.stderr = "Exception in thread main..."

            adapter.execute()

            log_calls = mock_log_handle.write.call_args_list
            assert any('[FAILURE] Tool crashed' in args[0] for args, _ in log_calls)
            assert any('Exception in thread main' in args[0] for args, _ in log_calls)

            stream_calls = mock_stream_handle.write.call_args_list
            assert any('sha_fail' in args[0] for args, _ in stream_calls)

    # [NEW] Test Case 7: Migration Warning
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_migration_warning(self, mock_lib):
        """
        Test 7: Migration Warning.
        Verify that the user is warned if a legacy .json file exists.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))

        # [FIX] Match signature for autospec=True (first arg is self/path_instance)
        def exists_side_effect(self):
            path_str = str(self)
            if path_str.endswith(".json"): return True
            if path_str.endswith(".jsonl"): return False
            return False

        with patch("pathlib.Path.exists", autospec=True, side_effect=exists_side_effect), \
                patch("builtins.print") as mock_print:

            adapter.get_output_path()

            print_calls = [args[0] for args, _ in mock_print.call_args_list]
            assert any("[MIGRATION NOTICE]" in msg for msg in print_calls)

    # [NEW] Test Case 8: SHA Filtering
    @patch("pipeline.utils.adapter_subprocess.run_command")
    @patch("pipeline.adapters.refm_adapt.RefactoringMinerAdapter._get_lib_path")
    def test_sha_filtering(self, mock_lib, mock_run):
        """
        Test 8: SHA Filtering.
        Verify that empty lines in git output are filtered out.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))
        mock_lib.return_value = Path("lib")

        mock_run.return_value = (True, "sha1\n\nsha2\n")

        commits = adapter._get_all_commits()

        assert len(commits) == 2
        assert "" not in commits

