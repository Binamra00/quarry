import json
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
    """Standard paths for general tests."""
    return {
        "ref": tmp_path / "ref.jsonl",
        "pmd": tmp_path / "pmd.jsonl",
        "lin": tmp_path / "lin.jsonl",
        "out": tmp_path / "output.parquet"
    }


def create_dummy_jsonl(path: Path, shas: list, sha_col: str):
    """Helper to create physical JSONL files for integrity testing."""
    with open(path, "w") as f:
        for sha in shas:
            record = {sha_col: sha, "other_data": "dummy"}
            f.write(json.dumps(record) + "\n")


# --- General Orchestration Tests ---

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

    # NOTE: The integrity check will run on empty/missing files here.
    # It should catch the FileNotFoundError internally and print a warning,
    # but NOT raise, allowing the test to proceed.

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
            patch("polars.scan_parquet") as mock_scan, \
            patch.object(engine, "_validate_data_integrity") as mock_validate:  # <--- [FIX] Mock this out

        # Setup mock for collect().write_parquet()
        mock_df = MagicMock()
        mock_collect.return_value = mock_df

        # Mock final verification
        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 5

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Assertions
    # Now this will be True because the integrity check didn't steal 2 calls
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

        def execute(self, ctx, data): return None

    engine = HeuristicEngine([BadStrategy()])

    # We mock print to suppress the integrity check warning for missing files
    with patch("builtins.print"), \
            pytest.raises(RuntimeError, match="Pipeline finished but no data"):
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])


# --- Integrity Check Tests (New) ---

def test_integrity_check_critical_failure(tmp_path, mock_paths):
    """
    Scenario: >50% of Refactoring Commits are missing PMD data.
    Expected: RuntimeError (Fail Fast).
    """
    # 1. Setup Data
    # Refactorings have 10 commits
    ref_shas = [f"sha_{i}" for i in range(10)]
    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")

    # PMD only has 2 commits (80% missing)
    pmd_shas = [f"sha_{i}" for i in range(2)]
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    # 2. Execution & Assertion
    with pytest.raises(RuntimeError) as excinfo:
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    assert "CRITICAL" in str(excinfo.value)
    assert "80.0% of refactoring data is missing" in str(excinfo.value)


def test_integrity_check_warning_only(tmp_path, mock_paths):
    """
    Scenario: <50% of Refactoring Commits are missing PMD data.
    Expected: Warning printed, but pipeline continues.
    """
    # 1. Setup Data
    # Refactorings have 10 commits
    ref_shas = [f"sha_{i}" for i in range(10)]
    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")

    # PMD has 8 commits (20% missing - Acceptable)
    pmd_shas = [f"sha_{i}" for i in range(8)]
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    # 2. Mock internals to allow run to finish
    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # 3. Assertions
    # Check that we saw the warning in the logs
    # We loop through calls to find the specific warning
    warning_printed = False
    for call_args in mock_print.call_args_list:
        if "WARNING: Data Mismatch Detected" in str(call_args):
            warning_printed = True
            break

    assert warning_printed, "Engine should have warned about mismatch"


def test_integrity_check_pass(tmp_path, mock_paths):
    """
    Scenario: 100% Data match.
    Expected: Success log, no warnings.
    """
    shas = ["a", "b", "c"]
    create_dummy_jsonl(mock_paths["ref"], shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Verify 100% integrity message
    success_printed = False
    for call_args in mock_print.call_args_list:
        if "Integrity Verified: 100% Coverage" in str(call_args):
            success_printed = True
            break

    assert success_printed


def test_integrity_check_io_failure(mock_paths):
    """
    Scenario: Files do not exist (IO Error during check).
    Expected: Check is skipped, pipeline proceeds (Graceful Degradation).
    """
    # DO NOT create files.
    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0

        # Should not raise
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Verify failure log
    failure_logged = False
    for call_args in mock_print.call_args_list:
        if "Integrity Check Skipped/Failed" in str(call_args):
            failure_logged = True
            break

    assert failure_logged