from typing import Protocol, Dict, Any, Optional
import polars as pl

class IHeuristicStrategy(Protocol):
    """
    The Protocol (Interface) that all Heuristic Strategies must implement.

    This ensures that the Heuristic Engine can orchestrate different scoring
    logic (AST Proximity, Complexity, etc.) without knowing their internal details.
    """

    @property
    def name(self) -> str:
        """
        Unique identifier for the heuristic (e.g., 'AST_Proximity').
        Used for column naming and logging.
        """
        ...

    @property
    def description(self) -> str:
        """
        Human-readable description of what this heuristic measures.
        """
        ...

    def execute(self, context: Dict[str, Any], data: Optional[pl.LazyFrame]) -> pl.LazyFrame:
        """
        The core logic. Receives the context (file paths) and the current data stream.

        Args:
            context (Dict[str, Any]): Configuration map containing file paths (refactorings_path, pmd_path, lineage_path).
            data (Optional[pl.LazyFrame]): The data passed down from the previous strategy in the chain.
                                           If None, this is the first strategy in the chain.

        Returns:
            pl.LazyFrame: The transformed dataframe with new score columns added.
        """
        ...