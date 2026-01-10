import sys  # Used for sys.maxsize to represent an unlimited batch size
from typing import List
from pathlib import Path
from pipeline.adapters.i_adapters import IAdapter
from pipeline.adapters.pmd_adapt import PMDAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
from pipeline.adapters.pmd_history_adapt import PMDHistoryAdapter


class ToolFactory:
    """
    Factory Method Pattern.
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = None) -> List[IAdapter]:
        adapters = []
        stage = stage.lower()

        # [FIX] Use sys.maxsize for explicit "Infinite" batch behavior
        if batch_size is None or batch_size <= 0:
            batch_size = sys.maxsize

        # 1. History Mining Tools (RefactoringMiner)
        if stage in ["history", "all", "refm"]:
            adapters.append(RefactoringMinerAdapter(target_repo_path))

        # 2. PMD Strategy Selection
        if stage == "all":
            # "All" means full history analysis using the robust batcher
            adapters.append(PMDHistoryAdapter(target_repo_path, batch_size))

        elif stage in ["static", "pmd"]:
            # Legacy snapshot
            adapters.append(PMDAdapter(target_repo_path))

        elif stage in ["pmd_history", "pmd_refm"]:
            # Explicit history request
            adapters.append(PMDHistoryAdapter(target_repo_path, batch_size))

        return adapters