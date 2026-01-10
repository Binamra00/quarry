import polars as pl
from pathlib import Path
from typing import List, Dict
from pipeline.heuristics.strategies.i_strategy import IHeuristicStrategy


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
            lineage_path: Path,  # [NEW] Argument
            output_path: Path) -> Dict[str, int]:

        if not self.strategies:
            raise ValueError("No strategies registered in HeuristicEngine.")

        print(f"🚀 [Engine] Initializing Lazy Stream...")

        # 1. Build the Context
        # We pass strings to ensure compatibility with Polars scan functions
        context = {
            "refactorings_path": str(refactoring_path),
            "pmd_path": str(pmd_path),
            "lineage_path": str(lineage_path)  # [NEW] Add to context
        }

        # 2. Pipeline Loop (Chain of Responsibility)
        current_data = None

        for strategy in self.strategies:
            print(f"   🧩 Executing Strategy: {strategy.name}")

            # Pass the baton: context + previous data -> new data
            current_data = strategy.execute(context, current_data)

        # 3. Save Results
        if current_data is None:
            raise RuntimeError("Pipeline finished but no data was generated.")

        print(f"   💾 Streaming results to {output_path.name}...")

        # SINK: We collect to memory here to get the count for logging.
        # For massive datasets, you might prefer sink_parquet directly.
        df_collected = current_data.collect()
        df_collected.write_parquet(output_path)

        return {
            "total_candidates": len(df_collected),
            "output_file": str(output_path)
        }