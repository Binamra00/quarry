import pytest
import polars as pl
from pipeline.heuristics.strategies.weighted_refactoring import WeightedRefactoringStrategy


@pytest.fixture
def mock_context():
    """
    Simulates the context injected by HeuristicEngine.
    We inject a small 'complexity_rules' map to prove the code reads it dynamically.
    """
    return {
        "refactorings_path": "dummy_path",
        "heuristic_seeds": {
            "complexity_rules": {
                # Standard Rule
                "Extract Class": [1.0, "High_Arch"],
                # Floss Rule (Testing Base Score)
                "Rename Method": [0.1, "Low_Floss"],
                # Custom Rule (Testing Config Injection)
                "Test Refactoring": [0.9, "Custom_Category"]
            }
        }
    }


def test_config_injection(mock_context):
    """
    Verifies that the strategy reads weights from the injected JSON config,
    not from hardcoded defaults.
    """
    # Create a dummy LazyFrame simulating the RefactoringMiner input
    data = pl.DataFrame({
        "commit_sha": ["1", "2"],
        "refactoring_type": ["Extract Class", "Test Refactoring"],
        "description": ["extract class A", "test refactoring B"]
    }).lazy()

    strategy = WeightedRefactoringStrategy()
    result = strategy.execute(mock_context, data).collect()

    # 1. Check Standard Rule
    row_arch = result.filter(pl.col("refactoring_type") == "Extract Class").row(0, named=True)
    assert row_arch["complexity_score"] == 1.0
    assert row_arch["impact_category"] == "High_Arch"

    # 2. Check Custom Rule (Proof of Config Injection)
    row_custom = result.filter(pl.col("refactoring_type") == "Test Refactoring").row(0, named=True)
    assert row_custom["complexity_score"] == 0.9
    assert row_custom["impact_category"] == "Custom_Category"


def test_escalation_logic_precision(mock_context):
    """
    Verifies the Context-Aware Logic:
    1. Rename Method + 'public' -> Escalate to 1.0
    2. Rename Method + 'private' -> Keep 0.1
    3. Rename Variable + 'public' -> Keep 0.1 (Precision Check)
    """
    data = pl.DataFrame({
        "refactoring_type": ["Rename Method", "Rename Method", "Rename Variable"],
        "description": [
            "Rename Method public getX() to public getY()",  # Case A: Breaking Change
            "Rename Method private foo() to private bar()",  # Case B: Floss
            "Rename Variable publicVar to privateVar"  # Case C: Variable (Should NOT escalate)
        ]
    }).lazy()

    strategy = WeightedRefactoringStrategy()
    result = strategy.execute(mock_context, data).collect()

    rows = result.to_dicts()

    # Case A: Public Rename Method -> Escalated
    assert rows[0]["complexity_score"] == 1.0
    assert rows[0]["impact_category"] == "High_API_Escalated"
    assert rows[0]["is_escalated"] == True
    assert rows[0]["escalation_reason"] == "public_api_rename"

    # Case B: Private Rename Method -> Floss
    assert rows[1]["complexity_score"] == 0.1
    assert rows[1]["impact_category"] == "Low_Floss"
    assert rows[1]["is_escalated"] == False

    # Case C: Public Variable Rename -> Floss (Proof of Precision)
    assert rows[2]["complexity_score"] == 0.1
    assert rows[2]["is_escalated"] == False