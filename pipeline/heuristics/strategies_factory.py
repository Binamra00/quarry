from typing import Dict, Type, List, Optional
from pipeline.heuristics.i_heuristics import IHeuristicStrategy  # [FIX] Updated Import
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy

class HeuristicFactory:
    """
    The Creator.
    Central registry for all available heuristic strategies.
    """

    # REGISTRY: Map string names to Class Types
    _REGISTRY: Dict[str, Optional[Type[IHeuristicStrategy]]] = {
        "AST_Proximity": ASTProximityStrategy,
        "Complexity": None,  # Placeholder for Phase 4.2
        "Criticality": None  # Placeholder for Phase 4.3
    }

    @staticmethod
    def create_strategies(strategy_names: List[str]) -> List[IHeuristicStrategy]:
        """
        Instantiates a list of strategies based on their string names.
        """
        instances = []
        for name in strategy_names:
            if name not in HeuristicFactory._REGISTRY:
                print(f" Warning: Unknown Heuristic Strategy '{name}' skipped.")
                continue

            strategy_class = HeuristicFactory._REGISTRY[name]

            if strategy_class is None:
                print(f" Warning: Heuristic '{name}' is defined but not yet implemented.")
                continue

            # Instantiate and add to list
            instances.append(strategy_class())

        return instances