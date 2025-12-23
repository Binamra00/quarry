from typing import List
from pathlib import Path
from pipeline.adapters.i_adapter import IAdapter
from pipeline.adapters.pmd_adapt import PMDAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
# [CLEANUP FIX 4.1] Import the correctly named adapter
from pipeline.adapters.pmd_history_adapt import PMDHistoryAdapter


class ToolFactory:
    """
    Factory Method Pattern.
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = 50) -> List[IAdapter]:
        adapters = []
        stage = stage.lower()

        # 1. History Mining Tools (RefactoringMiner)
        if stage in ["history", "all", "refm"]:
            adapters.append(RefactoringMinerAdapter(target_repo_path))

        # 2. PMD Strategy Selection

        # [CLEANUP FIX 4.2] Explicit Logic for "all"
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