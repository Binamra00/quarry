import polars as pl
import json
from pathlib import Path
from typing import List, Dict, Any
from polars.exceptions import PolarsError
from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline import config


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
        we have Quality (PMD) data for every refactoring event.

        [INDUSTRY STANDARD FIX]
        Uses purely Lazy operations (Anti-Join) to count missing rows
        without ever loading the dataset into Python memory.
        """
        print("    🔍 Verifying Data Integrity (Lazy Mode)...")

        try:
            # 1. Define Lazy Plans (No execution yet)
            q_refs = pl.scan_ndjson(refactoring_path).select("sha1")
            q_pmd = pl.scan_ndjson(pmd_path).select("sha")

            # 2. Check for Missing Context using an ANTI-JOIN
            # "Find rows in Refs that do NOT exist in PMD"
            # This runs entirely in the optimized Query Engine (Rust)
            missing_count = (
                q_refs.join(q_pmd, left_on="sha1", right_on="sha", how="anti")
                .select(pl.len())
                .collect()  # Only materializes a single integer!
                .item()
            )

            # 3. Get total count for ratio calculation
            total_refs = q_refs.select(pl.len()).collect().item()

            if total_refs == 0:
                print("    ℹ️  No refactoring commits found. Skipping integrity check.")
                return

            if missing_count > 0:
                print(f"    ⚠️  WARNING: Data Mismatch Detected!")
                print(f"       Total Refactorings: {total_refs}")
                print(f"       ❌ MISSING CONTEXT: {missing_count} commits have Refactorings but NO PMD data.")

                miss_ratio = missing_count / total_refs

                if miss_ratio > self.fail_fast_threshold:
                    raise RuntimeError(
                        f"CRITICAL: {miss_ratio:.1%} of refactoring data is missing PMD context. "
                        "Pipeline aborted to prevent invalid training data."
                    )
            else:
                print("    ✅ Integrity Verified: 100% Coverage.")

        except FileNotFoundError as e:
            print(f"    ⚠️  Integrity Check Skipped (Missing File): {e}")
            return

        except (PolarsError, KeyError) as e:
            print(f"    ❌ Integrity Check Failed (IO/Schema Error): {e}")
            raise RuntimeError("Aborting heuristics pipeline due to IO/Schema issues.") from e

    def _load_heuristic_seeds(self) -> Dict[str, Any]:
        """Loads the JSON configuration for heuristics."""
        # config.HEURISTICS_PATH is already defined in your config.py
        seeds_path = config.HEURISTICS_PATH

        try:
            with open(seeds_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"    ⚠️ Warning: Could not load heuristic_seeds.json ({e}). Strategies will use defaults.")
            return {}

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

        # --- [ADDITION STARTS HERE] ---
        # Load Configuration
        seeds_config = self._load_heuristic_seeds()
        # --- [ADDITION ENDS HERE] ---

        # 1. Build the Context
        context = {
            "refactorings_path": str(refactoring_path),
            "pmd_path": str(pmd_path),
            "lineage_path": str(lineage_path),
            "heuristic_seeds": seeds_config
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