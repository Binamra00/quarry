from abc import ABC, abstractmethod
import statistics
from typing import List, Dict


# ==========================================
# 1. Refactoring Logic Strategy (The History Model)
# ==========================================

class IRefactoringLogic(ABC):
    """
    Strategy Interface for Refactoring Metrics.
    Implement this to test different mathematical definitions of evolution.
    """

    @abstractmethod
    def is_impure(self, churn: int, operation_count: int) -> bool:
        pass

    @abstractmethod
    def calculate_density(self, ref_commits: int, total_commits: int) -> float:
        pass

    @abstractmethod
    def calculate_purity_score(self, pure_commits: int, total_ref_commits: int) -> float:
        pass


class StandardRefactoringLogic(IRefactoringLogic):
    """
    The 'Standard' Model: Linear relationships.
    """

    def __init__(self, churn_sensitivity: int = 20):
        self.sensitivity = churn_sensitivity

    def is_impure(self, churn: int, operation_count: int) -> bool:
        # Formula: Churn > Ops * Sensitivity
        return churn > (operation_count * self.sensitivity)

    def calculate_density(self, ref_commits: int, total_commits: int) -> float:
        if total_commits == 0: return 0.0
        return (ref_commits / total_commits) * 100

    def calculate_purity_score(self, pure_commits: int, total_ref_commits: int) -> float:
        if total_ref_commits == 0: return 0.0
        return (pure_commits / total_ref_commits) * 100


# ==========================================
# 2. Static Analysis Logic Strategy (The Debt Model)
# ==========================================

class IStaticAnalysisLogic(ABC):
    """
    Strategy Interface for PMD/Smell Metrics.
    Implement this to test different ways of weighting technical debt.
    """

    @abstractmethod
    def calculate_density(self, total_smells: int, file_count: int) -> float:
        pass

    @abstractmethod
    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        pass

    @abstractmethod
    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        pass


class StandardStaticLogic(IStaticAnalysisLogic):
    """
    The 'Standard' Model: Arithmetic Mean and Linear Density.
    """

    def calculate_density(self, total_smells: int, file_count: int) -> float:
        if file_count == 0: return 0.0
        return total_smells / file_count

    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        # Standard: Arithmetic Mean
        if not scores: return 0.0
        return statistics.mean(scores)

    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        # Standard: Top N by absolute count
        return dict(sorted(file_map.items(), key=lambda x: x[1], reverse=True)[:limit])


class WeightedStaticLogic(IStaticAnalysisLogic):
    """
    Example of a Research Variant:
    Maybe you want to weight complexity exponentially?
    """

    def calculate_density(self, total_smells: int, file_count: int) -> float:
        # Variant: Penalize small files? (Just an example)
        if file_count == 0: return 0.0
        return total_smells / (file_count ** 0.5)

    def calculate_complexity_aggregation(self, scores: List[int]) -> float:
        # Variant: Median might be more robust to outliers than Mean
        if not scores: return 0.0
        return statistics.median(scores)

    def identify_hotspots(self, file_map: Dict[str, int], limit: int) -> Dict[str, int]:
        return dict(sorted(file_map.items(), key=lambda x: x[1], reverse=True)[:limit])