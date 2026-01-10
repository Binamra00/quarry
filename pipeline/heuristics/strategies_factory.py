from typing import List, Dict, Type
from pipeline.heuristics.i_heuristics import IHeuristicStrategy

# Import your concrete strategies here
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


# from pipeline.heuristics.strategies.complexity import ComplexityStrategy (Future)

class HeuristicFactory:
    """
    The Creator.
    Central registry for all available heuristic strategies.
    """

    # REGISTRY: Map string names to Class Types
    _REGISTRY: Dict[str, Type[IHeuristicStrategy]] = {
        "AST_Proximity": ASTProximityStrategy,
        "Complexity": None,  # Placeholder for Heuristic A
        "Criticality": None  # Placeholder for Heuristic C
    }

    @staticmethod
    def create_strategies(strategy_names: List[str]) -> List[IHeuristicStrategy]:
        """
        Instantiates a list of strategies based on their string names.
        """
        instances = []
        for name in strategy_names:
            if name not in HeuristicFactory._REGISTRY:
                print(f"⚠️ Warning: Unknown Heuristic Strategy '{name}' skipped.")
                continue

            strategy_class = HeuristicFactory._REGISTRY[name]

            if strategy_class is None:
                # Graceful handling for not-yet-implemented heuristics
                print(f"⚠️ Warning: Heuristic '{name}' is defined but not yet implemented.")
                continue

            # Instantiate and add to list
            instances.append(strategy_class())

        return instances