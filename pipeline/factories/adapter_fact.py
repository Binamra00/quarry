from typing import List
from pathlib import Path
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
    def create_adapters(stage: str, target_repo_path: Path) -> List[IAdapter]:
        """
        Generates a list of tool adapters based on the requested stage.

        Args:
            stage (str): The pipeline stage ('all', 'history', 'static', 'refm', 'pmd').
            target_repo_path (Path): The repository object to be analyzed.

        Returns:
            List[IAdapter]: A list of instantiated adapters ready for execution.
        """
        adapters = []

        # Normalize stage string to handle aliases if needed
        stage = stage.lower()

        # 1. History Mining Tools
        if stage in ["history", "all", "refm"]:
            # [DEPENDENCY INJECTION] Pass the target path to the adapter
            adapters.append(RefactoringMinerAdapter(target_repo_path))

        # 2. Static Analysis Tools
        if stage in ["static", "all", "pmd"]:
            # [DEPENDENCY INJECTION] Pass the target path to the adapter
            adapters.append(PMDAdapter(target_repo_path))

        # Future:
        # if stage in ["security", "all"]:
        #     adapters.append(SonarQubeAdapter(target_repo_path))

        return adapters