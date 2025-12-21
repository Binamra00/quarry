from typing import List
from pipeline.adapters.i_adapter import IAdapter
from pipeline.adapters.pmd_adapt import PMDAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter


class ToolFactory:
    """
    Factory Method Pattern.
    Encapsulates the instantiation logic for analysis tools.
    Decouples the Client (main.py) from Concrete Products (Adapters).
    """

    @staticmethod
    def create_adapters(stage: str) -> List[IAdapter]:
        """
        Generates a list of tool adapters based on the requested stage.

        Args:
            stage (str): The pipeline stage ('all', 'history', 'static', 'refm', 'pmd').

        Returns:
            List[IAdapter]: A list of instantiated adapters ready for execution.
        """
        adapters = []

        # Normalize stage string to handle aliases if needed
        stage = stage.lower()

        # 1. History Mining Tools
        if stage in ["history", "all", "refm"]:
            adapters.append(RefactoringMinerAdapter())

        # 2. Static Analysis Tools
        if stage in ["static", "all", "pmd"]:
            adapters.append(PMDAdapter())

        # Future:
        # if stage in ["security", "all"]:
        #     adapters.append(SonarQubeAdapter())

        return adapters