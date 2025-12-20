from abc import ABC, abstractmethod
from pathlib import Path

class IAdapter(ABC):
    """
    The Universal Interface for all analysis tools (RefactoringMiner, PMD, SonarQube, etc.).
    Follows the Open/Closed Principle: Open for new tools, Closed for modification of main.py.
    """

    @abstractmethod
    def get_tool_name(self) -> str:
        """Returns the display name of the tool (e.g., 'RefactoringMiner')."""
        pass

    @abstractmethod
    def execute(self) -> bool:
        """
        Runs the analysis logic.
        Returns:
            bool: True if execution was successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_output_path(self) -> Path:
        """Returns the path where the tool saves its results."""
        pass