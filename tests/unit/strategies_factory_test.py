from pipeline.heuristics.strategies_factory import HeuristicFactory
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


def test_registry_contains_core_strategies():
    """Verify standard strategies are registered."""
    available = HeuristicFactory.get_available_strategies()
    assert "AST_Proximity" in available
    assert "Complexity" in available
    assert "Criticality" in available


def test_create_valid_strategy():
    """Verify factory returns correct instance for valid name."""
    strategies = HeuristicFactory.create_strategies(["AST_Proximity"])
    assert len(strategies) == 1
    assert isinstance(strategies[0], ASTProximityStrategy)
    assert strategies[0].name == "AST_Proximity"


def test_create_multiple_strategies():
    """Verify factory handles lists correctly."""
    # It should return the implemented one and skip the unknown one
    strategies = HeuristicFactory.create_strategies(["AST_Proximity", "UnknownStrategy"])
    assert len(strategies) == 1
    assert isinstance(strategies[0], ASTProximityStrategy)


def test_ignore_unknown_strategy(capsys):
    """Verify factory warns and skips unknown names."""
    strategies = HeuristicFactory.create_strategies(["FakeStrategy"])
    assert len(strategies) == 0

    # Check stdout for warning
    captured = capsys.readouterr()
    assert "Unknown Heuristic Strategy 'FakeStrategy' skipped" in captured.out


def test_ignore_unimplemented_strategy(capsys):
    """Verify factory warns and skips placeholders (None in registry)."""
    # [FIX] "Complexity" is now implemented, so we check "Criticality" (Phase 4.3)
    strategies = HeuristicFactory.create_strategies(["Criticality"])

    assert len(strategies) == 0

    # Optional: Check if warning was printed
    captured = capsys.readouterr()
    assert "is defined but not yet implemented" in captured.out