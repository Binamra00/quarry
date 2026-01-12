import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import polars as pl
from polars.exceptions import PolarsError

from pipeline.heuristics.polars_engine import HeuristicEngine
from pipeline.heuristics.i_heuristics import IHeuristicStrategy


# --- Mocks ---

class MockStrategy(IHeuristicStrategy):
    """A dummy strategy that just passes data through."""

    def __init__(self, name="MockStrategy"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Mock Description"

    def execute(self, context, data):
        # Return a dummy LazyFrame if none exists, else pass it through
        if data is None:
            return pl.DataFrame({"col": [1]}).lazy()
        return data


@pytest.fixture
def mock_paths(tmp_path):
    return {
        "ref": tmp_path / "ref.jsonl",
        "pmd": tmp_path / "pmd.jsonl",
        "lin": tmp_path / "lin.jsonl",
        "out": tmp_path / "output.parquet"
    }


# --- Tests ---

def test_engine_initialization_empty_list():
    """Engine should reject empty strategy lists."""
    engine = HeuristicEngine([])
    with pytest.raises(ValueError, match="No strategies registered"):
        engine.run(Path("a"), Path("b"), Path("c"), Path("out"))


def test_chain_execution(mock_paths):
    """Verify engine runs all strategies in order."""
    s1 = MockStrategy("S1")
    s2 = MockStrategy("S2")

    # Spy on the execute methods
    s1.execute = MagicMock(side_effect=s1.execute)
    s2.execute = MagicMock(side_effect=s2.execute)

    engine = HeuristicEngine([s1, s2])

    # Mock the Polars sink/scan operations to avoid IO
    with patch("polars.LazyFrame.sink_parquet") as mock_sink, \
            patch("polars.scan_parquet") as mock_scan:
        # Mock final count check
        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 10

        result = engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Verify both strategies were called
    assert s1.execute.called
    assert s2.execute.called
    assert result["total_candidates"] == 10


def test_fallback_logic(mock_paths):
    """Verify engine falls back to memory (collect) if streaming (sink) fails."""
    strategy = MockStrategy()
    engine = HeuristicEngine([strategy])

    with patch("polars.LazyFrame.sink_parquet", side_effect=PolarsError("Streaming failed")) as mock_sink, \
            patch("polars.LazyFrame.collect") as mock_collect, \
            patch("polars.scan_parquet") as mock_scan:
        # Setup mock for collect().write_parquet()
        mock_df = MagicMock()
        mock_collect.return_value = mock_df

        # Mock final verification
        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 5

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Assertions
    mock_sink.assert_called_once()  # Tried streaming
    mock_collect.assert_called_once()  # Fell back to memory
    mock_df.write_parquet.assert_called_once()  # Wrote to disk via fallback


def test_no_data_generated(mock_paths):
    """Engine should raise error if strategies return None."""

    class BadStrategy(IHeuristicStrategy):
        @property
        def name(self): return "Bad"

        @property
        def description(self): return "Bad"

        def execute(self, ctx, data): return None  # Returns Nothing!

    engine = HeuristicEngine([BadStrategy()])

    with pytest.raises(RuntimeError, match="Pipeline finished but no data"):
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])