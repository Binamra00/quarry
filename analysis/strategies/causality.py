# analysis/strategies/causality.py
import polars as pl
import logging
from .i_analyzer import IAnalyzer

logger = logging.getLogger(__name__)


class CausalityAnalyzer(IAnalyzer):
    """Generates Table 4 (Complete Matrix) and implicitly provides data for Table 1."""

    @property
    def name(self) -> str:
        return "table4_complete_matrix"

    def analyze(self, df: pl.DataFrame) -> pl.DataFrame:
        logger.info("🧠 Running Causality Analysis...")

        # Convert Booleans to Integers
        calc_df = df.with_columns([
            pl.col("spatial_overlap").cast(pl.Int8).alias("Touched"),
            pl.col("left_smell").cast(pl.Int8).alias("Pre_Smell"),
            pl.col("right_smell").cast(pl.Int8).alias("Post_Smell")
        ])

        # Group by Scenarios
        matrix = (
            calc_df.group_by(["Touched", "Pre_Smell", "Post_Smell"])
            .agg(pl.len().alias("Count"))
            .sort(["Touched", "Pre_Smell", "Post_Smell"], descending=True)
        )

        # Labeling
        def get_label(touched, pre, post):
            if touched == 1:
                if pre == 1 and post == 1: return "Scenario 2: Failed Fix"
                if pre == 1 and post == 0: return "Scenario 1: True Fix"
                if pre == 0 and post == 1: return "Scenario 3: Introduction"
                if pre == 0 and post == 0: return "Clean (Safe Refactoring)"
            return "Noise (Irrelevant)"

        return matrix.with_columns(
            pl.struct(["Touched", "Pre_Smell", "Post_Smell"])
            .map_elements(lambda x: get_label(x["Touched"], x["Pre_Smell"], x["Post_Smell"]), return_dtype=pl.Utf8)
            .alias("Scenario_Label")
        )