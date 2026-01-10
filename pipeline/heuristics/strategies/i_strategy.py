from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import polars as pl


class IHeuristicStrategy(ABC):
    """
    Interface for all Heuristic Strategies.
    Implements the Chain of Responsibility pattern.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly name for logging (e.g. 'AST_Proximity')."""
        pass

    @abstractmethod
    def execute(self, context: Dict[str, Any], data: Optional[pl.LazyFrame]) -> pl.LazyFrame:
        """
        Executes the strategy logic.

        :param context: A dictionary containing global inputs (e.g., file paths).
        :param data: The DataFrame from the previous step in the pipeline.
                     (None if this is the first strategy).
        :return: A transformed Polars LazyFrame.
        """
        pass