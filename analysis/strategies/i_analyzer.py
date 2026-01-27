# analysis_engine/strategies/interface.py
from abc import ABC, abstractmethod
import polars as pl


class IAnalyzer(ABC):
    """Interface that all analysis strategies must implement."""

    @abstractmethod
    def analyze(self, df: pl.DataFrame) -> pl.DataFrame:
        """Process the data and return a result DataFrame."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name of this analysis (used for filenames)."""
        pass