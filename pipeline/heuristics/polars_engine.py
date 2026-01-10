import polars as pl
from pathlib import Path
from typing import List, Dict

from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class HeuristicEngine:
    """
    The High-Performance Correlator.

    Responsibilities:
    1. Loads the massive datasets lazily (using DTOLoader).
    2. Joins Refactorings and Smells on 'commit_sha'.
    3. Executes the registered Heuristic Strategies.
    4. Streams the result to a Parquet file (Ground Truth).
    """

    def __init__(self, strategies: List[IHeuristicStrategy]):
        self.strategies = strategies

    def run(self,
            refactoring_path: Path,
            pmd_path: Path,
            output_path: Path) -> Dict[str, int]:

        print(f"🚀 [Engine] Initializing Lazy Stream...")

        # 1. Lazy Load (No memory cost yet)
        refm_lazy = DTOLoader.load_refactorings(refactoring_path)
        pmd_lazy = DTOLoader.load_smells(pmd_path)

        # 2. The Great Join (Inner Join on Commit SHA)
        # We only care about commits where BOTH a refactoring AND a smell exist.
        joined_lazy = (
            pmd_lazy.join(
                refm_lazy,
                on="commit_sha",
                how="inner",
                suffix="_ref"  # Handle name collisions (e.g., file_path -> file_path_ref)
            )
        )

        # 3. Apply Heuristics (Transformation Pipeline)
        # Each strategy adds its own score column to the lazy plan.
        processed_lazy = joined_lazy
        for strategy in self.strategies:
            print(f"   🧩 Registering Strategy: {strategy.name}")
            processed_lazy = strategy.calculate(processed_lazy)

        # 4. Materialization (The Heavy Lifting)
        # This is where Polars actually reads the files, joins them, and writes output.
        print(f"   💾 Streaming results to {output_path.name}...")

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # SINK: Stream directly to Parquet (efficient compression)
        # usage of sink_parquet is preferred over collect() for memory safety
        try:
            processed_lazy.sink_parquet(output_path)
        except Exception as e:
            print(f"⚠️ Streaming failed (Parquet sink error): {e}")
            print("   Fallback: collecting to memory first...")
            processed_lazy.collect().write_parquet(output_path)

        # 5. Verification
        # We perform a cheap metadata read to count rows
        final_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        print(f"✅ Ground Truth Generated: {final_count} correlated candidates.")
        return {"total_candidates": final_count}