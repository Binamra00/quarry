import pytest
import polars as pl
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


def test_ast_proximity_logic():
    """
    Verifies the mathematical soundness of Heuristic B (Interval Intersection).
    We test 6 geometric scenarios to ensure the 'overlap' logic is robust.
    """

    # 1. SETUP: Construct a Synthetic Truth Table
    # We simulate a 'joined' dataframe with various overlap scenarios.
    data = pl.DataFrame({
        "scenario": [
            "Exact Match",
            "Refactoring Engulfs Smell (Subset)",
            "Smell Engulfs Refactoring (Superset)",
            "Partial Overlap (Head)",
            "Touching Boundaries (Edge Case)",
            "Completely Disjoint"
        ],
        # Smell Intervals [start, end]
        "start_line": [10, 12, 10, 10, 10, 10],
        "end_line": [20, 15, 20, 20, 20, 20],

        # Refactoring Intervals [start_ref, end_ref]
        "start_line_ref": [10, 10, 12, 15, 21, 50],
        "end_line_ref": [20, 20, 15, 25, 30, 60],

        # Expected Result (1.0 = Match, 0.0 = No Match)
        "expected_score": [1.0, 1.0, 1.0, 1.0, 0.0, 0.0]
    }).lazy()

    # 2. EXECUTE: Run the Strategy
    strategy = ASTProximityStrategy()
    result_frame = strategy.calculate(data).collect()

    # 3. VERIFY: Check results row-by-row
    print("\n--- Heuristic B Logic Trace ---")

    # Extract columns for assertion
    scenarios = result_frame["scenario"].to_list()
    scores = result_frame["score_AST_Proximity"].to_list()
    expected = result_frame["expected_score"].to_list()

    for i, scenario in enumerate(scenarios):
        actual = scores[i]
        target = expected[i]

        # Visual Log for the Developer
        print(f"[{'✅' if actual == target else '❌'}] {scenario}: Expected {target}, Got {actual}")

        # Hard Assertion
        assert actual == target, f"Logic failed for scenario: {scenario}"


def test_empty_input_resilience():
    """
    Ensures the strategy does not crash on empty inputs (Defense in Depth).
    """
    # Create empty dataframe with correct schema
    empty_data = pl.DataFrame({
        "start_line": [], "end_line": [],
        "start_line_ref": [], "end_line_ref": []
    }, schema={
        "start_line": pl.Int64, "end_line": pl.Int64,
        "start_line_ref": pl.Int64, "end_line_ref": pl.Int64
    }).lazy()

    strategy = ASTProximityStrategy()
    result = strategy.calculate(empty_data).collect()

    assert result.height == 0
    assert "score_AST_Proximity" in result.columns