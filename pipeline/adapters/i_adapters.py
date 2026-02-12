from abc import ABC, abstractmethod
from pathlib import Path
from typing import Set

class IAdapter(ABC):
    """
    The Universal Interface for all analysis tools (RefactoringMiner, PMD, SonarQube, etc.).
    Follows the Open/Closed Principle: Open for new tools, Closed for modification of main.py.
    """

    def __init__(self, target_repo_path: Path):
        """
        Constructor Injection.
        Args:
            target_repo_path (Path): The specific repository to analyze.
        """
        self.target_repo_path = target_repo_path

    @abstractmethod
    def get_tool_name(self) -> str:
        """Returns the display name of the tool (e.g., 'RefactoringMiner')."""
        pass

    @abstractmethod
    def execute(self) -> bool:
        """
        Runs the analysis logic using self.target_repo_path.
        Returns:
            bool: True if execution was successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_output_path(self) -> Path:
        """Returns the path where the tool saves its results."""
        pass

    def get_log_path(self) -> Path:
        """
        Returns the path where the raw execution log should be saved.
        Default: A .log file next to the output .json file.
        """
        # Example: outputs/pmd_candidates.json -> outputs/pmd_candidates.log
        return self.get_output_path().with_suffix(".log")

    def set_sampling_filter(self, sampled_shas: Set[str]):
        """
        [HOOK] Optional configuration for adapters that support sampling.

        Default implementation does nothing (No-Op).
        Concrete classes (like PMDHistoryAdapter) can override this to
        apply the filter logic.
        """
        pass