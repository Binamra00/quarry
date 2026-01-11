import polars as pl
from pathlib import Path
from typing import List, Dict
from polars.exceptions import PolarsError
from pipeline.heuristics.i_heuristics import IHeuristicStrategy


# [FIX] Removed 'from pipeline.heuristics.dto_loader import DTOLoader' as it was unused

class HeuristicEngine:
    """
    The Orchestrator for Phase 4.
    Executes a dynamic pipeline of strategies (Chain of Responsibility).
    """

    def __init__(self, strategies: List[IHeuristicStrategy]):
        self.strategies = strategies

    def run(self,
            refactoring_path: Path,
            pmd_path: Path,
            lineage_path: Path,
            output_path: Path) -> Dict[str, int]:

        if not self.strategies:
            raise ValueError("No strategies registered in HeuristicEngine.")

        print(f" [Engine] Initializing Lazy Stream...")

        # 1. Build the Context
        context = {
            "refactorings_path": str(refactoring_path),
            "pmd_path": str(pmd_path),
            "lineage_path": str(lineage_path)
        }

        # 2. Pipeline Loop
        current_data = None
        for strategy in self.strategies:
            print(f"    Executing Strategy: {strategy.name}")
            current_data = strategy.execute(context, current_data)

        # 3. Save Results
        if current_data is None:
            raise RuntimeError("Pipeline finished but no data was generated.")

        print(f"    Streaming results to {output_path.name}...")

        try:
            # SINK: Attempt efficient streaming first
            current_data.sink_parquet(output_path)

        except PolarsError as e:
            # Fallback to in-memory collection if streaming fails (e.g., complex joins)
            print(f" Streaming failed (Polars Error): {e}")
            print("    Fallback: collecting to memory first...")
            current_data.collect().write_parquet(output_path)

        # [FIX] Moved out of the 'except' block so it runs regardless of the save method
        # Verification Step: Count rows from the file we just wrote
        final_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        return {
            "total_candidates": final_count,
            "output_file": str(output_path)
        }