import sys
from typing import List
from pathlib import Path
from pipeline import config
from pipeline.adapters.i_adapters import IAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter

# Notice we DO NOT import CK, PMD, or History adapters here at the top!

class ToolFactory:
    """
    Factory Method Pattern with Lazy Loading.
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = None) -> List[IAdapter]:
        adapters = []
        stage = stage.lower()

        if batch_size is None or batch_size <= 0:
            batch_size = sys.maxsize

        # 1. History Mining Tools (RefactoringMiner)
        if stage in ["refm", "all"]:
            adapters.append(RefactoringMinerAdapter(target_repo_path))

        # 2. PMD Strategy (Legacy/Alternative)
        # Runs if explicitly requested, OR if "all" is called and PMD is the active tool
        if stage in ["pmd_history", "pmd"] or (stage == "all" and config.STRUCTURAL_TOOL == "pmd"):
            if stage == "pmd":
                from pipeline.adapters.pmd_adapt import PMDAdapter
                adapters.append(PMDAdapter(target_repo_path))
            else:
                from pipeline.adapters.pmd_history_adapt import PMDHistoryAdapter
                adapters.append(PMDHistoryAdapter(target_repo_path, batch_size))

        # 3. CK Structural Taxonomy (New)
        # Runs if explicitly requested, OR if "all" is called and CK is the active tool
        if stage == "ck" or (stage == "all" and config.STRUCTURAL_TOOL == "ck"):
            from pipeline.adapters.ck_adapt import CkAdapter
            adapters.append(CkAdapter(target_repo_path, batch_size))

        # 4. Evolutionary Ledger (New)
        if stage in ["ledger", "all"]:
            from pipeline.adapters.ledger_adapt import LedgerAdapter
            adapters.append(LedgerAdapter(target_repo_path, batch_size))

        return adapters