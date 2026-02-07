# pipeline/analyzer/engine.py
import polars as pl
from pathlib import Path
from typing import List, Dict, Any, Optional
from .contracts import IAnalyzerStrategy, IRelevanceSpec
from .specs import JsonRelevanceSpec
from .loader import AnalyzerDataLoader  # <--- NEW IMPORT


class AnalyzerEngine:
    """
    The Orchestrator for Phase 5 (Analysis).
    It manages the lifecycle of the analysis strategies and ensures data integrity.
    """

    def __init__(self, strategies: List[IAnalyzerStrategy], config_path: Path):
        """
        Args:
            strategies: A list of analysis strategies to execute (e.g., CausalImpact).
            config_path: Path to the relevance_matrix.json file.
        """
        self.strategies = strategies
        self.config_path = config_path
        self._spec: Optional[IRelevanceSpec] = None

        # Pre-load the specification to fail fast if config is missing
        try:
            self._spec = JsonRelevanceSpec(config_path)
            print(f"   [Analyzer] ✅ Loaded Relevance Matrix from {config_path.name}")
        except Exception as e:
            print(f"   [Analyzer] ❌ Failed to load Relevance Matrix: {e}")
            raise

    def run(self, input_path: Path, output_path: Path) -> None:
        """
        Executes all configured strategies on the input dataset.

        Args:
            input_path: Path to ground_truth.parquet.
            output_path: Path where the final verified dataset will be saved.
        """
        print(f"🚀 [Analyzer] Starting Analysis on {input_path.name}...")

        # 1. Load Data using the DTO Loader (Standardization happens here)
        # [CHANGE] We replaced pl.scan_parquet with our robust loader
        try:
            lf = AnalyzerDataLoader.load_ground_truth(input_path)
        except Exception as e:
            print(f"   ❌ Data Loading Failed: {e}")
            raise

        # 2. Build Context
        context = {
            "relevance_spec": self._spec,
            "input_path": input_path,
            "output_path": output_path
        }

        # 3. Execute Strategies Sequentially
        # Each strategy takes the LazyFrame, transforms it, and returns a new one.
        for strategy in self.strategies:
            print(f"   ⚙️  Executing Strategy: {strategy.name()}...")
            try:
                lf = strategy.execute(lf, context)
            except Exception as e:
                print(f"   ❌ Strategy '{strategy.name()}' failed: {e}")
                raise

        # 4. Sink to Disk (Trigger Execution)
        # This is where the actual computation happens (Polars Lazy Evaluation).
        print(f"   💾 Saving results to {output_path.name}...")
        try:
            lf.sink_parquet(output_path)
            print(f"   ✅ Analysis Complete. Verified data saved.")

            # Optional: Quick Integrity Check
            self._print_summary(output_path)

        except Exception as e:
            print(f"   ❌ Failed to save output: {e}")
            raise

    def _print_summary(self, output_path: Path):
        """Helper to print a quick summary of the results."""
        df = pl.read_parquet(output_path)
        if "causal_verdict" in df.columns:
            print("\n   📊 Causal Verification Summary:")
            print(df.group_by("causal_verdict").len())