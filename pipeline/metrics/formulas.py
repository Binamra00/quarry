from abc import ABC, abstractmethod
import statistics
from typing import List, Dict


# ==========================================
# 1. Refactoring Logic Strategy
# ==========================================

class IRefactoringLogic(ABC):
    @abstractmethod
    def is_impure(self, churn: int, operation_count: int) -> bool:
        pass

    @abstractmethod
    def calculate_density(self, ref_commits: int, total_commits: int) -> float:
        """Returns density as a raw ratio (0.0 to 1.0)."""
        pass

    @abstractmethod
    def calculate_purity_score(self, pure_commits: int, total_ref_commits: int) -> float:
        """Returns purity as a raw ratio (0.0 to 1.0)."""
        pass


class StandardRefactoringLogic(IRefactoringLogic):
    """
    The 'Standard' Model: Linear relationships for churn and density.
    """

    def __init__(self, churn_sensitivity: int = 20):
        self.sensitivity = churn_sensitivity

    def is_impure(self, churn: int, operation_count: int) -> bool:
        return churn > (operation_count * self.sensitivity)

    def calculate_density(self, ref_commits: int, total_commits: int) -> float:
        # [FIX] Multi-line zero check
        if total_commits == 0:
            return 0.0
        return float(ref_commits) / total_commits

    def calculate_purity_score(self, pure_commits: int, total_ref_commits: int) -> float:
        # [FIX] Multi-line zero check
        if total_ref_commits == 0:
            return 0.0
        return float(pure_commits) / total_ref_commits


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