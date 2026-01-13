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
        self.strategies = strategies
        self.fail_fast_threshold = fail_fast_threshold

    def _validate_data_integrity(self, refactoring_path: str, pmd_path: str) -> None:
        """
        Internal Helper: Performs a fail-fast check to ensure
        we have Quality (PMD) data for every refactoring event.

        Args:
            refactoring_path (str): Path to the refactoring events dataset
                (expected to be in NDJSON/JSONL format).
            pmd_path (str): Path to the PMD metrics dataset
                (expected to be in NDJSON/JSONL format).

        Raises:
            RuntimeError: If the proportion of refactoring events without
            corresponding PMD data exceeds the configured fail-fast threshold
            (i.e., when data is considered critically corrupted).
        """
        print("    🔍 Verifying Data Integrity...")

        try:
            # 1. Lazy scan of input files, then materialize unique SHAs for comparison
            # We use scan_ndjson to avoid loading full records eagerly, but `.collect()`
            # below will load the distinct SHA columns into memory. This is acceptable
            # for our expected scale (thousands of commits, not millions).
            refactoring_shas = pl.scan_ndjson(refactoring_path).select("sha1").unique().collect().get_column("sha1")
            pmd_shas = pl.scan_ndjson(pmd_path).select("sha").unique().collect().get_column("sha")

            # Convert to Python sets for fast comparison
            refactoring_set = set(refactoring_shas)
            pmd_set = set(pmd_shas)

            # Guard Clause: Prevent division by zero if no refactorings exist
            if len(refactoring_set) == 0:
                print("    ℹ️  No refactoring commits found. Skipping integrity check.")
                return

            # 2. Find Missing Ground Truth
            missing_ground_truth = refactoring_set - pmd_set

            if len(missing_ground_truth) > 0:
                print(f"    ⚠️  WARNING: Data Mismatch Detected!")
                print(f"       Refactorings Found: {len(refactoring_set)} commits")
                print(f"       PMD Profiles Found: {len(pmd_set)} commits")
                print(f"       ❌ MISSING CONTEXT: {len(missing_ground_truth)} commits have Refactorings but NO PMD data.")

                # Fail-Fast Principle: Stop if data is significantly corrupted
                miss_ratio = len(missing_ground_truth) / len(refactoring_set)

                # Use the configured class attribute
                if miss_ratio > self.fail_fast_threshold:
                    raise RuntimeError(
                        f"CRITICAL: {miss_ratio:.1%} of refactoring data is missing PMD context. "
                        "Pipeline aborted to prevent invalid training data."
                    )
            else:
                print("    ✅ Integrity Verified: 100% Coverage.")

        except (PolarsError, FileNotFoundError, KeyError) as e:
            # Only catch IO/Parsing/Schema errors. Critical Logic errors (RuntimeError) bubble up.
            print(f"    ⚠️  Integrity Check Skipped/Failed (IO/Schema Error): {e}")
            print("       Continuing with caution...")

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
            # Fallback to in-memory collection if streaming fails
            print(f" Streaming failed (Polars Error): {e}")
            print("    Fallback: collecting to memory first...")
            current_data.collect().write_parquet(output_path)

        # Verification Step
        final_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        return {
            "total_candidates": final_count,
            "output_file": str(output_path)
        }