from unittest.mock import MagicMock
from pipeline.commands.adapter_cmd import RunToolCommand


def test_delegates_execution_success():
    """Verify execute() returns True if Adapter succeeds."""
    # 1. Mock the Adapter
    mock_adapter = MagicMock()
    mock_adapter.execute.return_value = True
    mock_adapter.get_tool_name.return_value = "MockTool"

    # 2. Run Command
    cmd = RunToolCommand(mock_adapter)
    result = cmd.execute()

    # 3. Verify Delegation
    assert result is True
    mock_adapter.execute.assert_called_once()


def test_delegates_execution_failure():
    """Verify execute() returns False if Adapter fails."""
    mock_adapter = MagicMock()
    mock_adapter.execute.return_value = False
    mock_adapter.get_tool_name.return_value = "MockTool"

    cmd = RunToolCommand(mock_adapter)
    result = cmd.execute()

    assert result is False
    mock_adapter.execute.assert_called_once()


def test_delegates_tool_name():
    """Verify get_tool_name() fetches from Adapter."""
    mock_adapter = MagicMock()
    mock_adapter.get_tool_name.return_value = "SuperMiner 3000"

    cmd = RunToolCommand(mock_adapter)

    assert cmd.get_tool_name() == "SuperMiner 3000"
    mock_adapter.get_tool_name.assert_called()