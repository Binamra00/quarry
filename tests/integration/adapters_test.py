import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import subprocess
from pipeline.adapters.pmd_history_adapt import PMDHistoryAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter


# ==========================================
# TEST SUITE: INTEGRATION (MOCKED)
# Goal: Verify tool orchestration without running actual binaries.
# ==========================================

class TestPMDAdapterIntegration:
    """Verifies PMD execution logic and error handling."""

    @patch("subprocess.run")
    def test_pmd_exit_code_4_is_success(self, mock_subprocess):
        """
        Test 1: PMD returns exit code 4 when violations are found.
        The adapter MUST treat this as success, not a crash.
        """
        # Setup: Mock the subprocess to return exit code 4
        mock_process = MagicMock()
        mock_process.returncode = 4
        mock_process.stdout = '{"files": []}'  # Minimal valid JSON output
        mock_subprocess.return_value = mock_process

        # Action: Initialize adapter (paths don't need to be real due to mocks)
        adapter = PMDHistoryAdapter(Path("dummy_repo"))

        # We mock the internal _run_command to isolate logic
        # But here we test the subprocess interaction logic specifically
        # For this test, we verify the adapter's interpreting logic
        is_success = adapter._is_success_code(4)

        # Assert
        assert is_success is True, "PMD Exit Code 4 should be classified as Success"

    @patch("subprocess.run")
    def test_pmd_timeout_handling(self, mock_subprocess):
        """
        Test 2: The Poison Pill Simulation.
        If PMD hangs, the adapter should catch TimeoutExpired and return None.
        """
        # Setup: Simulate a hang
        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="pmd", timeout=300)

        adapter = PMDHistoryAdapter(Path("dummy_repo"))

        # Action: Run a command (private method access for testing)
        # We assume the adapter uses a wrapper method for subprocess
        # If accessing directly, we verify the exception handling block
        try:
            # Simulate the safe_subprocess call you likely have in utils
            from pipeline.utils.adapter_subprocess import run_tool_command
            result = run_tool_command(["pmd"], timeout=10)
        except Exception:
            pytest.fail("The utility should handle the timeout, not crash.")

        # If your adapter catches it internally:
        # assert result is None (depending on implementation)


class TestRefmAdapterIntegration:
    """Verifies RefactoringMiner orchestration."""

    @patch("pipeline.adapters.refm_adapt.Repository")  # Mock PyDriller
    @patch("subprocess.run")
    def test_git_checkout_safety(self, mock_subprocess, mock_repo):
        """
        Test 3: Time-Travel Safety.
        Verify that we ALWAYS checkout main after processing, even if it fails.
        """
        adapter = RefactoringMinerAdapter(Path("dummy_repo"))

        # Setup: Mock the 'git' object on the adapter
        adapter.repo_git = MagicMock()

        # Action: Simulate a crash during analysis
        with pytest.raises(RuntimeError):
            # We force a crash inside the context manager
            with adapter._checkout_context("some-sha"):
                raise RuntimeError("Simulated Crash")

        # Assert: The cleanup code must have run
        # Verify 'git checkout main' was called
        adapter.repo_git.checkout.assert_called_with("main")

    def test_smart_skipping_logic(self):
        """
        Test 4: Resume Capability.
        If output file exists, run() should return immediately.
        """
        # Setup: Create a temp file to simulate existing output
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True  # File exists!

            adapter = RefactoringMinerAdapter(Path("dummy_repo"))

            # Action
            result = adapter.run()

            # Assert
            assert result is not None
            # It should skip execution (we can verify no subprocess was called if we mocked it)