from abc import ABC, abstractmethod
import polars as pl
from typing import Dict, Any


class IRelevanceSpec(ABC):
    """
    Contract for the Specification Pattern.
    Determines if a specific Refactoring Type is theoretically capable
    of fixing a specific Smell Rule.
    """

    @abstractmethod
    def is_relevant(self, refactoring_type: str, smell_rule: str) -> bool:
        """
        Returns True if the refactoring type is mapped to the smell rule.
        """
        pass


class IAnalyzerStrategy(ABC):
    """
    Contract for the Strategy Pattern.
    Defines a distinct analysis pass (e.g., Causal Impact, Survival Analysis).
    """

    @abstractmethod
    def name(self) -> str:
        """Returns the unique name of this strategy (e.g., 'causal_impact')."""
        pass

    @abstractmethod
    def execute(self, df: pl.LazyFrame, context: Dict[str, Any]) -> pl.LazyFrame:
        """
        Performs the analysis on the LazyFrame.

        Args:
            df: The input Polars LazyFrame (e.g., ground_truth.parquet).
            context: A dictionary containing shared resources (e.g., paths, specs).

        Returns:
            A transformed Polars LazyFrame representing the analysis result.
        """
        pass