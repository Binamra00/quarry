import pytest
from unittest.mock import patch, MagicMock
import sys
from pipeline.main import main


@pytest.fixture
def mock_sys_argv():
    def _mock(args):
        return patch.object(sys, 'argv', ["main.py"] + args)

    return _mock


@pytest.fixture
def mock_dependencies():
    with patch("pipeline.main.allocate_tools.provision", return_value=True), \
            patch("pipeline.main.RepositoryLoader"), \
            patch("pipeline.main.adapter_subprocess.run_command", return_value=("master", True)), \
            patch("pipeline.main.RepoMetrics"), \
            patch("pipeline.main.MetadataAdapter"), \
            patch("pipeline.main.ToolFactory.create_adapters", return_value=[]), \
            patch("pipeline.main.RunHeuristicsCommand"), \
            patch("pipeline.main.RefmMetrics"), \
            patch("pipeline.main.PMDMetrics"), \
            patch("pipeline.main.config") as mock_config:
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
    3. Exits cleanly (SystemExit 0).
    """
    with mock_sys_argv(["--stage", "heuristics"]), \
            patch("pipeline.main.RunToolCommand") as mock_tool_cmd, \
            patch("pipeline.main.RunHeuristicsCommand") as mock_heur_cmd:
        # Expect Success (Exit Code 0)
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0

        # MetadataAdapter should NOT be called in 'heuristics' stage
        mock_tool_cmd.assert_not_called()

        # Heuristics command SHOULD be called
        mock_heur_cmd.assert_called_once()