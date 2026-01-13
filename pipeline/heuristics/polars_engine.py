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

    def _validate_data_integrity(self, refactoring_path: str, pmd_path: str):
        """
        Internal Helper: Performs a Fail-Fast check to ensure
        we have Quality (PMD) data for every Refactoring event.
        Uses LazyFrames to minimize memory overhead.
        """
        print("    🔍 Verifying Data Integrity...")

        try:
            # 1. Lazy Scan (Metadata only, no full load)
            # Use scan_ndjson (Newline Delimited JSON) or scan_parquet depending on your input
            # Assuming inputs are JSONL based on your project status
            refm_shas = pl.scan_ndjson(refactoring_path).select("sha1").unique().collect().get_column("sha1")
            pmd_shas = pl.scan_ndjson(pmd_path).select("sha").unique().collect().get_column("sha")

            # Convert to python sets for fast comparison
            refm_set = set(refm_shas)
            pmd_set = set(pmd_shas)

            # 2. Find Missing Ground Truth
            missing_ground_truth = refm_set - pmd_set

            if len(missing_ground_truth) > 0:
                print(f"    ⚠️  WARNING: Data Mismatch Detected!")
                print(f"       Refactorings Found: {len(refm_set)} commits")
                print(f"       PMD Profiles Found: {len(pmd_set)} commits")
                print(
                    f"       ❌ MISSING CONTEXT: {len(missing_ground_truth)} commits have Refactorings but NO PMD data.")

                # Fail-Fast Principle: Stop if data is significantly corrupted
                miss_ratio = len(missing_ground_truth) / len(refm_set)
                if miss_ratio > 0.5:
                    raise RuntimeError(
                        f"CRITICAL: {miss_ratio:.1%} of refactoring data is missing PMD context. "
                        "Pipeline aborted to prevent invalid training data."
                    )
            else:
                print("    ✅ Integrity Verified: 100% Coverage.")


        # [FIX] Catch only relevant errors, or check for our Critical error

        except (PolarsError, FileNotFoundError) as e:

            print(f"    ⚠️  Integrity Check Skipped/Failed (IO Error): {e}")

            print("       Continuing with caution...")

        # [FIX] Explicitly re-raise the RuntimeError we generated above

        except RuntimeError as e:

            if "CRITICAL" in str(e):
                raise e

            print(f"    ⚠️  Runtime Error during check: {e}")

    def run(self,
            refactoring_path: Path,
            pmd_path: Path,
            lineage_path: Path,
            output_path: Path) -> Dict[str, int]:

        if not self.strategies:
            raise ValueError("No strategies registered in HeuristicEngine.")

        print(f" [Engine] Initializing Lazy Stream...")

        # --- [FIX] CALL THE VALIDATION HERE ---
        self._validate_data_integrity(str(refactoring_path), str(pmd_path))
        # --------------------------------------

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

        # Verification Step: Count rows from the file we just wrote
        final_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()

        return {
            "total_candidates": final_count,
            "output_file": str(output_path)
        }