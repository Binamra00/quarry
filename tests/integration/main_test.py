import pytest
from unittest.mock import patch, MagicMock
import sys
from pipeline.main import main


class FakeToolCommand:
    """Helper to mock RunToolCommand instances with specific success/fail outcomes."""
    def __init__(self, adapter=None, name="MockTool", success=True):
        # NOTE: `adapter` is accepted to mirror the RunToolCommand interface but is not used.
        self.name = name
        self.success = success

    def get_tool_name(self):
        return self.name

    def execute(self):
        return self.success


# Helper class to satisfy isinstance() checks
class FakeHeuristicsCommand:
    def __init__(self, target_repo, strategies=None):
        pass

    def execute(self):
        return True

    def get_tool_name(self):
        return "HeuristicEngine"


@pytest.fixture
def mock_sys_argv():
    """Helper to mock command line arguments."""

    def _mock(args):
        return patch.object(sys, 'argv', ["main.py"] + args)

    return _mock


@pytest.fixture
def mock_dependencies():
    """
    Mock all external interactions (FS, Git, Tools).
    """
    with patch("pipeline.main.allocate_tools.provision", return_value=True), \
            patch("pipeline.main.RepositoryLoader"), \
            patch("pipeline.main.adapter_subprocess.run_command", return_value=(True, "master")), \
            patch("pipeline.main.RepoMetrics"), \
            patch("pipeline.main.MetadataAdapter"), \
            patch("pipeline.main.ToolFactory.create_adapters", return_value=[]), \
            patch("pipeline.main.RunHeuristicsCommand", new=FakeHeuristicsCommand), \
            patch("pipeline.main.RefmMetrics"), \
            patch("pipeline.main.PMDMetrics"), \
            patch("pipeline.main.config") as mock_config:
        # Setup Config Mocks
        mock_config.VALID_STAGES = ["all", "heuristics", "history", "refm", "pmd", "static"]
        mock_config.ensure_dirs = MagicMock()
        mock_config.WORKSPACE_ROOT = MagicMock()
        mock_config.WORKSPACE_ROOT.name = "mock_workspace"
        yield


def test_stage_heuristics_command_list(mock_sys_argv, mock_dependencies):
    """
    Verify --stage heuristics:
    1. Skips MetadataAdapter.
    2. Includes RunHeuristicsCommand.
    3. Exits cleanly.
    """
    # 1. REMOVE patch("pipeline.main.RunHeuristicsCommand") from this list
    with mock_sys_argv(["--stage", "heuristics"]), \
            patch("pipeline.main.RunToolCommand") as mock_tool_cmd:
        # 2. Spy on the Fake Class __init__
        # [FIX] Use return_value=None because __init__ must return None.
        # Since FakeHeuristicsCommand.__init__ is empty (pass), bypassing it is safe.
        with patch.object(FakeHeuristicsCommand, '__init__', return_value=None) as mock_init:
            main()

            # MetadataAdapter should NOT be called in 'heuristics' stage
            mock_tool_cmd.assert_not_called()

            # Heuristics command SHOULD be called
            mock_init.assert_called_once()


def test_stage_all_command_list(mock_sys_argv, mock_dependencies):
    """
    Verify --stage all:
    1. Includes MetadataAdapter.
    2. Includes Mining Adapters.
    3. Includes Heuristics.
    4. Exits cleanly.
    """
    # 1. REMOVE patch("pipeline.main.RunHeuristicsCommand") from this list
    with mock_sys_argv(["--stage", "all"]), \
            patch("pipeline.main.RunToolCommand") as mock_tool_cmd, \
            patch("pipeline.main.MetadataAdapter") as mock_meta_adapter:
        # 2. Spy on the Fake Class __init__
        # [FIX] Use return_value=None (see above)
        with patch.object(FakeHeuristicsCommand, '__init__', return_value=None) as mock_init:
            main()

            # MetadataAdapter should be instantiated
            mock_meta_adapter.assert_called()

            # RunToolCommand should be called (at least for Metadata)
            assert mock_tool_cmd.call_count >= 1

            # Heuristics command should be called
            mock_init.assert_called_once()

def test_invalid_heuristic_exit(mock_sys_argv, mock_dependencies):
    """Verify script exits with code 1 if an invalid heuristic is requested."""
    with mock_sys_argv(["--stage", "heuristics", "--heuristic", "A"]), \
            patch("pipeline.main.HeuristicFactory.get_available_strategies", return_value=[]), \
            pytest.raises(SystemExit) as pytest_wrapped_e:
        main()

    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == 1


def test_circuit_breaker_failure(mock_sys_argv, mock_dependencies):
    """
    CRITICAL TEST: Verify Circuit Breaker Logic.
    1. Setup: Upstream tool (RefactoringMiner) FAILS.
    2. Expectation: Script Exits with Code 1 and Heuristics are SKIPPED.
    """
    with mock_sys_argv(["--stage", "all"]), \
            patch("pipeline.main.RunToolCommand") as mock_tool_cmd, \
            patch("pipeline.main.MetadataAdapter"), \
            patch(
                "pipeline.main.ToolFactory.create_adapters") as mock_create_adapters:  # [TEST SETUP] We need to mock this return value

        # 1. Setup the Mining Phase to produce 2 dummy adapters
        mock_create_adapters.return_value = ["refm_adapter", "pmd_adapter"]

        # 2. Setup the Command Instances (NOT Booleans)
        # Command 1: Metadata (Success)
        cmd_meta = FakeToolCommand(name="Metadata", success=True)
        # Command 2: RefMiner (FAILURE) <--- The Poison Pill
        cmd_refm = FakeToolCommand(name="RefactoringMiner", success=False)
        # Command 3: PMD (Success)
        cmd_pmd = FakeToolCommand(name="PMD", success=True)

        # 3. Assign these objects as the side_effect of the Constructor
        mock_tool_cmd.side_effect = [cmd_meta, cmd_refm, cmd_pmd]

        # 4. Spy on Heuristics
        with patch.object(FakeHeuristicsCommand, 'execute') as mock_heur_exec:
            # Expect SystemExit(1) because the pipeline is unhealthy
            with pytest.raises(SystemExit) as e:
                main()
            assert e.value.code == 1

            # ASSERTION: The Heuristic Engine must NOT have run
            mock_heur_exec.assert_not_called()
