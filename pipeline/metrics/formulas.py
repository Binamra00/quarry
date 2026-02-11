from abc import ABC, abstractmethod
import statistics
from typing import List, Dict


# ==========================================
# 1. Refactoring Logic Strategy (STREAMING EDITION)
# ==========================================

class IRefactoringAnalysisLogic(ABC):
    """
    Strategy Interface for calculating Refactoring metrics in a Streaming Architecture.
    """

    @abstractmethod
    def calculate_commit_purity(self, refactorings: List[dict], total_churn: int) -> float:
        """Returns a purity score (0.0 to 1.0) for a single commit."""
        pass

    @abstractmethod
    def calculate_purity_aggregation(self, purity_scores: List[float]) -> float:
        """Aggregates individual commit scores into a repository-wide average (0-100)."""
        pass

    @abstractmethod
    def identify_hotspots(self, locations_map: Dict[str, int], limit: int) -> Dict[str, int]:
        """Returns the top N most refactored files."""
        pass


class StandardRefactoringLogic(IRefactoringAnalysisLogic):
    """
    Standard implementation for RefactoringMiner metrics.
    """

    def __init__(self, churn_sensitivity: int = 20):
        self.churn_sensitivity = churn_sensitivity

    def calculate_commit_purity(self, refactorings: List[dict], total_churn: int) -> float:
        if not refactorings:
            return None

        # Heuristic: Each refactoring 'explains' some churn (e.g., 20 lines).
        explained_churn = len(refactorings) * self.churn_sensitivity

        if total_churn <= 0:
            return 1.0  # Pure refactoring (renames often have 0 line churn)

        ratio = explained_churn / total_churn
        return min(ratio, 1.0)  # Cap at 1.0

    def calculate_purity_aggregation(self, purity_scores: List[float]) -> float:
        if not purity_scores:
            return 0.0
        # Return average purity percentage (0-100)
        return (sum(purity_scores) / len(purity_scores)) * 100

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


class WeightedStaticLogic(IStaticAnalysisLogic):
    """
    Alternative weighting model for static analysis metrics.

    This implementation applies a non-linear density calculation and uses the
    median for complexity aggregation to reduce the influence of outliers and
    very large or very small files. It can be used in place of
    ``StandardStaticLogic`` when you want a more robust aggregation of
    complexity scores.

    Note: This strategy is experimental.
    """

    def calculate_density(self, total_smells: int, file_count: int) -> float:
        if file_count == 0:
            return 0.0
        return total_smells / (file_count ** 0.5)

    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        if not scores:
            return 0.0
        return statistics.median(scores)

    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        return dict(sorted(file_map.items(), key=lambda x: x[1], reverse=True)[:limit])