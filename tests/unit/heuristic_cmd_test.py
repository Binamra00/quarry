import pytest
from unittest.mock import patch
from pipeline.commands.heuristic_cmd import RunHeuristicsCommand


@pytest.fixture
def mock_repo():
    return "toy_repo"


@pytest.fixture
def mock_paths(tmp_path):
    """Creates dummy input files to simulate a valid state."""
    (tmp_path / "refactorings_toy_repo.jsonl").touch()
    (tmp_path / "pmd_history_toy_repo.jsonl").touch()
    (tmp_path / "commit_lineage_toy_repo.jsonl").touch()
    return tmp_path


def test_missing_inputs_returns_false(mock_repo, tmp_path):
    """Scenario: User forgot to run previous stages (files missing)."""
    # Patch config to point to an empty temp dir
    with patch("pipeline.config.OUTPUTS_PATH", tmp_path):
        cmd = RunHeuristicsCommand(mock_repo)

        # Should return False because files don't exist
        assert cmd.execute() is False


def test_successful_execution(mock_repo, mock_paths):
    """Scenario: All inputs exist, Factory returns strategies, Engine runs ok."""

    with patch("pipeline.config.OUTPUTS_PATH", mock_paths):
        cmd = RunHeuristicsCommand(mock_repo)

        # Mock the external dependencies (Factory & Engine)
        with patch("pipeline.commands.heuristic_cmd.HeuristicFactory") as mock_factory, \
                patch("pipeline.commands.heuristic_cmd.HeuristicEngine") as mock_engine_cls:
            # Setup: Factory returns a list, Engine returns success dict
            mock_factory.create_strategies.return_value = ["MockStrategy"]
            mock_engine_instance = mock_engine_cls.return_value
            mock_engine_instance.run.return_value = {"total_candidates": 99}

            # Execution
            result = cmd.execute()

            # Assertions
            assert result is True
            mock_engine_instance.run.assert_called_once()

            # Verify correct paths were passed to the engine
            call_kwargs = mock_engine_instance.run.call_args[1]
            assert call_kwargs["refactoring_path"].name == "refactorings_toy_repo.jsonl"
            assert call_kwargs["lineage_path"].name == "commit_lineage_toy_repo.jsonl"


def test_no_valid_strategies(mock_repo, mock_paths):
    """Scenario: User requested strategies that don't exist."""

    with patch("pipeline.config.OUTPUTS_PATH", mock_paths):
        cmd = RunHeuristicsCommand(mock_repo)

        with patch("pipeline.commands.heuristic_cmd.HeuristicFactory") as mock_factory:
            # Factory returns empty list
            mock_factory.create_strategies.return_value = []

            assert cmd.execute() is False


def test_engine_exception_handling(mock_repo, mock_paths):
    """Scenario: Engine crashes (e.g., OOM or Corrupt Data)."""

    with patch("pipeline.config.OUTPUTS_PATH", mock_paths):
        cmd = RunHeuristicsCommand(mock_repo)

        with patch("pipeline.commands.heuristic_cmd.HeuristicFactory") as mock_factory, \
                patch("pipeline.commands.heuristic_cmd.HeuristicEngine") as mock_engine_cls:
            mock_factory.create_strategies.return_value = ["MockStrategy"]

            # Engine raises Exception
            mock_engine_instance = mock_engine_cls.return_value
            mock_engine_instance.run.side_effect = RuntimeError("Critical Failure")

            # Command should catch it and return False (not crash)
            assert cmd.execute() is False