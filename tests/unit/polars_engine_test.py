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
    """Verify the engine rejects an empty list of strategies."""
    engine = HeuristicEngine([])
    with pytest.raises(ValueError, match="No strategies registered"):
        engine.run(Path("a"), Path("b"), Path("c"), Path("out"))


def test_chain_execution(mock_paths):
    """Verify engine runs all strategies in order and passes data context."""
    s1 = MockStrategy("S1")
    s2 = MockStrategy("S2")

    s1.execute = MagicMock(side_effect=s1.execute)
    s2.execute = MagicMock(side_effect=s2.execute)

    engine = HeuristicEngine([s1, s2])

    with patch("polars.LazyFrame.sink_parquet") as mock_sink, \
            patch("polars.scan_parquet") as mock_scan, \
            patch.object(engine,
                         "_validate_data_integrity") as mock_validate:  # Mock integrity check to avoid relying on file-based validation

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 10
        result = engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    assert s1.execute.called
    assert s2.execute.called
    assert result["total_candidates"] == 10
    mock_validate.assert_called_once()


def test_fallback_logic(mock_paths):
    """Verify engine falls back to memory (collect) if streaming (sink) fails."""
    strategy = MockStrategy()
    engine = HeuristicEngine([strategy])

    with patch("polars.LazyFrame.sink_parquet", side_effect=PolarsError("Streaming failed")) as mock_sink, \
            patch("polars.LazyFrame.collect") as mock_collect, \
            patch("polars.scan_parquet") as mock_scan, \
            patch.object(engine,
                         "_validate_data_integrity") as mock_validate:  # Mock integrity checks to focus on fallback behavior

        mock_df = MagicMock()
        mock_collect.return_value = mock_df
        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 5

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Now this will be True because the integrity check is mocked out and doesn't consume additional calls
    mock_sink.assert_called_once()
    mock_collect.assert_called_once()
    mock_df.write_parquet.assert_called_once()


def test_no_data_generated(mock_paths):
    """Verify the engine raises an error when strategies return None and no data is produced."""

    class BadStrategy(IHeuristicStrategy):
        @property
        def name(self): return "Bad"

        @property
        def description(self): return "Bad"

        def execute(self, ctx, data): return None

    engine = HeuristicEngine([BadStrategy()])

    with patch("builtins.print"), \
            pytest.raises(RuntimeError, match="Pipeline finished but no data"):
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])


# --- Integrity Check Tests (New) ---

def test_integrity_check_critical_failure(mock_paths):
    """
    Scenario: >50% of Refactoring Commits are missing PMD data.
    Expected: RuntimeError (Fail Fast).
    """
    # 1. Setup Data - Explicitly defining sets to ensure test robustness
    ref_shas = [f"sha_{i}" for i in range(10)]  # 10 commits
    pmd_shas = [f"sha_{i}" for i in range(2)]  # Only 2 overlap (0, 1)

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    # 2. Execution & Assertion
    with pytest.raises(RuntimeError) as excinfo:
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    msg = str(excinfo.value)
    assert "CRITICAL" in msg

    # Calculate expected percentage dynamically to avoid magic string brittleness
    expected_missing_pct = (1 - len(pmd_shas) / len(ref_shas)) * 100
    assert f"{expected_missing_pct:.1f}% of refactoring data is missing" in msg


def test_integrity_check_warning_only(mock_paths):
    """
    Scenario: <50% of Refactoring Commits are missing PMD data.
    Expected: Warning printed, but pipeline continues.
    """
    # 1. Setup Data
    ref_shas = [f"sha_{i}" for i in range(10)]
    # PMD has 8 commits overlapping ref_shas; sha_8 and sha_9 are missing (20% missing - Acceptable)
    pmd_shas = [f"sha_{i}" for i in range(8)]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    # 2. Mock internals to allow run to finish
    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # 3. Assertions
    warning_printed = False
    for call_args in mock_print.call_args_list:
        if "WARNING: Data Mismatch Detected" in str(call_args):
            warning_printed = True
            break

    assert warning_printed, "Engine should have warned about mismatch"


def test_integrity_check_exact_boundary(mock_paths):
    """
    Scenario: Exactly 50% of Refactoring Commits are missing PMD data.
    Expected: Warning printed, but NO RuntimeError (Boundary Condition).
    """
    # 1. Setup Data: 10 refactorings, 5 overlaps -> 50% missing
    ref_shas = [f"sha_{i}" for i in range(10)]
    pmd_shas = [f"sha_{i}" for i in range(5)]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    # 2. Execution - Should NOT raise
    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # 3. Assertions
    warning_printed = False
    for call_args in mock_print.call_args_list:
        if "WARNING: Data Mismatch Detected" in str(call_args):
            warning_printed = True
            break

    assert warning_printed, "Engine should warn at 50% boundary"


def test_integrity_check_pass(mock_paths):
    """
    Scenario: All refactoring commits have corresponding PMD data (100% coverage).
    Expected: Integrity check passes, success message is printed, and pipeline continues.
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

    success_printed = False
    for call_args in mock_print.call_args_list:
        if "Integrity Verified: 100% Coverage" in str(call_args):
            success_printed = True
            break

    assert success_printed, "Engine should have printed success message for 100% coverage"


def test_integrity_check_pmd_superset(mock_paths):
    """
    Scenario: PMD has MORE data than Refactorings (Superset).
    Expected: Pass (We only care that Refactorings have context, not vice-versa).
    """
    # Refactorings: A, B
    ref_shas = ["a", "b"]
    # PMD: A, B, C (Extra 'C' should be ignored)
    pmd_shas = ["a", "b", "c"]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # Assertion: Should pass with 100% coverage
    success_printed = False
    for call_args in mock_print.call_args_list:
        if "Integrity Verified: 100% Coverage" in str(call_args):
            success_printed = True
            break

    assert success_printed, "Extra PMD data should not cause failure"


def test_integrity_check_io_failure(mock_paths):
    """
    Scenario: Files do not exist (IO Error during check).
    Expected: Check is skipped, pipeline proceeds (Graceful Degradation).
    """
    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0

        # Should not raise
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    failure_logged = False
    for call_args in mock_print.call_args_list:
        if "Integrity Check Skipped/Failed" in str(call_args):
            failure_logged = True
            break

    assert failure_logged, "Engine should have logged IO failure during integrity check"