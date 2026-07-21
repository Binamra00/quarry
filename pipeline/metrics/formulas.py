from abc import ABC, abstractmethod
import statistics
from typing import List, Dict


# ==========================================
# 1. Refactoring Logic Strategy (STREAMING EDITION)
# ==========================================

class IRefactoringAnalysisLogic(ABC):
    """
    Strategy Interface for RefactoringMiner metrics.

    Scope note: this interface previously also declared commit-purity scoring, which
    depended on a per-commit churn map produced by an earlier full-history mining pass.
    That pass was removed when repository description became a read-only report, so the
    purity methods had no data source and no consumer and were dropped. The surviving
    responsibility is hotspot identification.
    """

    @abstractmethod
    def identify_hotspots(self, locations_map: Dict[str, int], limit: int) -> Dict[str, int]:
        """Returns the top N most refactored files."""
        pass


class StandardRefactoringLogic(IRefactoringAnalysisLogic):
    """
    Standard implementation for RefactoringMiner metrics: ranks the most frequently
    refactored files by occurrence count.
    """

    def identify_hotspots(self, locations_map: Dict[str, int], limit: int) -> Dict[str, int]:
        # Sort by frequency (descending) and take top N
        sorted_hotspots = sorted(locations_map.items(), key=lambda x: x[1], reverse=True)[:limit]
        return dict(sorted_hotspots)


# ==========================================
# 2. Static Analysis Logic Strategy
# ==========================================

class IStaticAnalysisLogic(ABC):
    @abstractmethod
    def calculate_density(self, total_smells: int, file_count: int) -> float:
        """
        Returns static-analysis density as a rate in smells per file.

        Unlike refactoring density, this is not a bounded ratio in [0.0, 1.0]:
        the value can exceed 1.0 when, on average, there are multiple smells
        per file.
        """
        pass

    @abstractmethod
    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        pass

    @abstractmethod
    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        pass


class StandardStaticLogic(IStaticAnalysisLogic):
    """
    Standard model for static analysis metrics using linear density and
    arithmetic-mean complexity aggregation.

    This strategy computes smell density as a simple rate of total smells per
    file and aggregates complexity scores using the arithmetic mean, providing
    a straightforward baseline.
    """

    def calculate_density(self, total_smells: int, file_count: int) -> float:
        if file_count == 0:
            return 0.0
        return float(total_smells) / file_count

    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        if not scores:
            return 0.0
        return statistics.mean(scores)

    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        return dict(sorted(file_map.items(), key=lambda x: x[1], reverse=True)[:limit])