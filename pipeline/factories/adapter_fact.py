from typing import List
from pathlib import Path
from pipeline.adapters.i_adapter import IAdapter
from pipeline.adapters.pmd_adapt import PMDAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
from pipeline.adapters.pmd_refm_adapt import PMDRefmAdapter


class ToolFactory:
    """
    Factory Method Pattern.
    Encapsulates the instantiation logic for analysis tools.
    Decouples the Client (main.py) from Concrete Products (Adapters).
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = 50) -> List[IAdapter]:
        """
        Generates a list of tool adapters based on the requested stage.

        Args:
            stage (str): The pipeline stage ('all', 'history', 'static', 'refm', 'pmd').
            target_repo_path (Path): The repository object to be analyzed.
            batch_size (int): Number of commits to process per batch (for PMD History).

        Returns:
            List[IAdapter]: A list of instantiated adapters ready for execution.
        """
        adapters = []
        stage = stage.lower()

        # 1. History Mining Tools (RefactoringMiner)
        if stage in ["history", "all", "refm"]:
            adapters.append(RefactoringMinerAdapter(target_repo_path))

        # 2. PMD Strategy Selection

        # OPTION A: Stateful History Batch (New Default)
        if stage == "all":
            # [INJECTION] Pass batch_size to the stateful adapter
            adapters.append(PMDRefmAdapter(target_repo_path, batch_size))

        # OPTION B: Snapshot Analysis (Legacy)
        elif stage in ["static", "pmd"]:
            adapters.append(PMDAdapter(target_repo_path))

        # OPTION C: Explicit History Request
        elif stage in ["pmd_history", "pmd_refm"]:
            adapters.append(PMDRefmAdapter(target_repo_path, batch_size))

        return adapters