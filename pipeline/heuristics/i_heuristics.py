from typing import Protocol, List
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

    def calculate(self, joined_frame: pl.LazyFrame) -> pl.LazyFrame:
        """
        The core logic. Receives the raw joined data (Refactorings + Smells).

        Args:
            joined_frame (pl.LazyFrame): A Polars LazyFrame containing the
                                         aligned commit_sha and file_path data.

        Returns:
            pl.LazyFrame: The original frame with a new 'score_<name>' column added.
        """
        ...