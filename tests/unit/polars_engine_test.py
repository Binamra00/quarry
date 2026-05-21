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


def create_dummy_jsonl(path: Path, shas: list, sha_col: str):
    with open(path, "w") as f:
        for sha in shas:
            record = {sha_col: sha, "other_data": "dummy"}
            f.write(json.dumps(record) + "\n")


# --- Tests ---

def test_engine_initialization_empty_list():
    """Verify the engine rejects an empty list of strategies."""
    engine = HeuristicEngine([])
    with pytest.raises(ValueError, match="No strategies registered"):
        engine.run(Path("a"), Path("b"), Path("c"), Path("out"))


def test_initialization_invalid_threshold():
    """Verify engine rejects invalid fail-fast thresholds."""
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        HeuristicEngine([MockStrategy()], fail_fast_threshold=1.5)


def test_chain_execution(mock_paths):
    """Verify engine runs all strategies and INJECTS CONFIGURATION."""
    s1 = MockStrategy("S1")

    # Mock the execute method to capture the context it receives
    s1.execute = MagicMock(side_effect=s1.execute)

    engine = HeuristicEngine([s1])

    # [NEW] Mock the config loader to return specific data
    mock_seeds = {"complexity_rules": {"Test": 1.0}}

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet"), \
            patch.object(engine, "_validate_data_integrity"), \
            patch.object(engine, "_load_heuristic_seeds", return_value=mock_seeds):  # <--- Mock Loader

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    # [VERIFY] Check if context contained the seeds
    call_args = s1.execute.call_args
    passed_context = call_args[0][0]  # First arg of first call

    assert "heuristic_seeds" in passed_context
    assert passed_context["heuristic_seeds"] == mock_seeds

def test_fallback_logic(mock_paths):
    """Verify engine falls back to memory (collect) if streaming (sink) fails."""
    strategy = MockStrategy()
    engine = HeuristicEngine([strategy])

    with patch("polars.LazyFrame.sink_parquet", side_effect=PolarsError("Streaming failed")) as mock_sink, \
            patch("polars.LazyFrame.collect") as mock_collect, \
            patch("polars.scan_parquet") as mock_scan, \
            patch.object(engine, "_validate_data_integrity") as mock_validate:
        # Mock integrity checks to focus on fallback behavior

        mock_df = MagicMock()
        mock_collect.return_value = mock_df
        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 5

        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

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


# --- Integrity Check Tests ---

def test_integrity_check_critical_failure(mock_paths):
    """Scenario: >50% of Refactoring Commits are missing PMD data."""
    ref_shas = [f"sha_{i}" for i in range(10)]
    pmd_shas = [f"sha_{i}" for i in range(2)]  # Only 2 overlap

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    with pytest.raises(RuntimeError) as excinfo:
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    msg = str(excinfo.value)
    assert "CRITICAL" in msg

    # [FIX] Use correct percentage formatting logic
    expected_missing_pct = 1 - len(pmd_shas) / len(ref_shas)
    assert f"{expected_missing_pct:.1%} of refactoring data is missing" in msg


def test_integrity_check_warning_only(mock_paths):
    """Scenario: <50% missing data triggers warning but continues."""
    ref_shas = [f"sha_{i}" for i in range(10)]
    pmd_shas = [f"sha_{i}" for i in range(8)]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    warning_printed = False
    for call_args in mock_print.call_args_list:
        if "WARNING: Data Mismatch Detected" in str(call_args):
            warning_printed = True
            break
    assert warning_printed, "Engine should have warned about mismatch"


def test_integrity_check_exact_boundary(mock_paths):
    """Scenario: Exactly 50% missing data (Boundary condition)."""
    ref_shas = [f"sha_{i}" for i in range(10)]
    pmd_shas = [f"sha_{i}" for i in range(5)]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    warning_printed = False
    for call_args in mock_print.call_args_list:
        if "WARNING: Data Mismatch Detected" in str(call_args):
            warning_printed = True
            break
    assert warning_printed, "Engine should warn at 50% boundary"


def test_integrity_check_pass(mock_paths):
    """Scenario: 100% Data match."""
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
    assert success_printed, "Engine should have printed success message"


def test_integrity_check_pmd_superset(mock_paths):
    """Scenario: PMD has MORE data than Refactorings (Superset)."""
    ref_shas = ["a", "b"]
    pmd_shas = ["a", "b", "c"]

    create_dummy_jsonl(mock_paths["ref"], ref_shas, "sha1")
    create_dummy_jsonl(mock_paths["pmd"], pmd_shas, "sha")

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
    assert success_printed, "Extra PMD data should not cause failure"


def test_integrity_check_missing_files(mock_paths):
    """
    Scenario: Files do not exist (FileNotFoundError).
    Expected: Check is skipped with warning, pipeline proceeds.
    """
    engine = HeuristicEngine([MockStrategy()])

    with patch("polars.LazyFrame.sink_parquet"), \
            patch("polars.scan_parquet") as mock_scan, \
            patch("builtins.print") as mock_print:

        mock_scan.return_value.select.return_value.collect.return_value.item.return_value = 0
        # Should not raise
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])

    skipped_log = False
    for call_args in mock_print.call_args_list:
        if "Integrity Check Skipped (Missing File)" in str(call_args):
            skipped_log = True
            break
    assert skipped_log, "Engine should log skipped check for missing files"


def test_integrity_check_corrupt_files(mock_paths):
    """
    Scenario: Files exist but are malformed (PolarsError/SchemaError).
    Expected: RuntimeError (Fail Fast).
    """
    # 1. Create the INVALID Ref file (The Trap)
    with open(mock_paths["ref"], "w") as f:
        f.write("THIS IS NOT JSONL")

    # 2. [FIX] Create a VALID PMD file (Required to bypass the "Missing File" check)
    with open(mock_paths["pmd"], "w") as f:
        f.write('{"sha": "dummy", "violation": "none"}\n')

    engine = HeuristicEngine([MockStrategy()])

    with pytest.raises(RuntimeError, match="Aborting heuristics pipeline"):
        engine.run(mock_paths["ref"], mock_paths["pmd"], mock_paths["lin"], mock_paths["out"])