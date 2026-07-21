import sys
from typing import List
from pathlib import Path
from pipeline import config
from pipeline.adapters.i_adapters import IAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter

# CK and Ledger adapters are lazy-loaded inside create_adapters (heavy imports).

class ToolFactory:
    """
    Factory Method Pattern with Lazy Loading.

    One miner per run -- there is no "all" stage. Each call builds exactly the adapter
    for the requested stage. universe_path scopes the history walkers (ledger, refm);
    CK sampling is applied separately by the caller via set_sampling_filter().
    """

    @staticmethod
    def create_adapters(stage: str, target_repo_path: Path, batch_size: int = None,
                        universe_path: str = None) -> List[IAdapter]:
        adapters = []
        stage = stage.lower()

        if batch_size is None or batch_size <= 0:
            batch_size = sys.maxsize

        # RefactoringMiner -- history walker; universe_path scopes the walk.
        if stage == "refm":
            adapters.append(RefactoringMinerAdapter(target_repo_path, universe_path=universe_path))

        # CK -- structural metrics; sampling is applied by the caller (set_sampling_filter).
        elif stage == "ck":
            from pipeline.adapters.ck_adapt import CkAdapter
            adapters.append(CkAdapter(target_repo_path, batch_size))

        # Evolutionary Ledger -- history walker; universe_path scopes the walk.
        elif stage == "ledger":
            from pipeline.adapters.ledger_adapt import LedgerAdapter
            adapters.append(LedgerAdapter(target_repo_path, batch_size, universe_path=universe_path))

        return adapters