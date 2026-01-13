import polars as pl
from pathlib import Path
from typing import List, Dict
from polars.exceptions import PolarsError
from pipeline.heuristics.i_heuristics import IHeuristicStrategy


class HeuristicEngine:
    """
    The Orchestrator for Phase 4.
    Executes a dynamic pipeline of strategies (Chain of Responsibility).
    """

    def __init__(self, strategies: List[IHeuristicStrategy], fail_fast_threshold: float = 0.5):
        """
        Args:
            strategies: List of strategies to execute.
            fail_fast_threshold: Ratio (0.0 - 1.0) of missing data allowed before crashing.
                                 Default 0.5 (50%).
        """
        if not (0.0 <= fail_fast_threshold <= 1.0):
            raise ValueError(f"fail_fast_threshold must be between 0.0 and 1.0, got {fail_fast_threshold}")

        self.strategies = strategies
        self.fail_fast_threshold = fail_fast_threshold

    def _validate_data_integrity(self, refactoring_path: str, pmd_path: str) -> None:
        """
        Internal Helper: Performs a fail-fast check to ensure
        we have Quality (PMD) data for every refactoring event
        """
        print("    🔍 Verifying Data Integrity...")

        try:
            # 1. Lazy scan of input files
            refactoring_shas = pl.scan_ndjson(refactoring_path).select("sha1").unique().collect().get_column("sha1")
            pmd_shas = pl.scan_ndjson(pmd_path).select("sha").unique().collect().get_column("sha")

            refactoring_set = set(refactoring_shas)
            pmd_set = set(pmd_shas)

            if len(refactoring_set) == 0:
                print("    ℹ️  No refactoring commits found. Skipping integrity check.")
                return

            # 2. Find Missing Ground Truth
            missing_ground_truth = refactoring_set - pmd_set

            if len(missing_ground_truth) > 0:
                print(f"    ⚠️  WARNING: Data Mismatch Detected!")
                print(f"       Refactorings Found: {len(refactoring_set)} commits")
                print(f"       PMD Profiles Found: {len(pmd_set)} commits")
                print(
                    f"       ❌ MISSING CONTEXT: {len(missing_ground_truth)} commits have Refactorings but NO PMD data.")

                miss_ratio = len(missing_ground_truth) / len(refactoring_set)

                # Use the configured instance-level fail-fast threshold
                if miss_ratio > self.fail_fast_threshold:
                    raise RuntimeError(
                        f"CRITICAL: {miss_ratio:.1%} of refactoring data is missing PMD context. "
                        "Pipeline aborted to prevent invalid training data."
                    )
            else:
                print("    ✅ Integrity Verified: 100% Coverage.")

        except FileNotFoundError as e:
            # Missing file: treat as graceful degradation but make it very visible.
            print(f"    ⚠️  Integrity Check Skipped (Missing File): {e}")
            print("       Proceeding without integrity verification for the missing dataset.")
            return

        except (PolarsError, KeyError) as e:
            # Parsing/Schema errors indicate potentially corrupted data: fail fast.
            print(f"    ❌ Integrity Check Failed (IO/Schema Error): {e}")
            raise RuntimeError(
                "Data integrity verification failed due to IO/Schema issues. "
                "Aborting heuristics pipeline to avoid using corrupted data."
            ) from e

    def run(self,
            refactoring_path: Path,
            pmd_path: Path,
            lineage_path: Path,
            output_path: Path) -> Dict[str, int]:

        if not self.strategies:
            raise ValueError("No strategies registered in HeuristicEngine.")

        print(f" [Engine] Initializing Lazy Stream...")

        # Run Validation
        self._validate_data_integrity(str(refactoring_path), str(pmd_path))

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
            print(f" Streaming failed (Polars Error): {e}")
            print("    Fallback: collecting to memory first...")
            current_data.collect().write_parquet(output_path)

        final_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        return {
            "total_candidates": final_count,
            "output_file": str(output_path)
        }