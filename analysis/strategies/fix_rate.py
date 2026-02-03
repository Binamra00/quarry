# analysis/strategies/smell_rules.py
import polars as pl
import logging
from .i_analyzer import IAnalyzer

logger = logging.getLogger(__name__)


class SmellRuleAnalyzer(IAnalyzer):
    """Generates Table 3: Fix Rate by Smell Rule (e.g., GodClass vs CyclomaticComplexity)."""

    @property
    def name(self) -> str:
        return "table3_smell_rules"

    def analyze(self, df: pl.DataFrame) -> pl.DataFrame:
        logger.info("🧠 Running Smell Rule Analysis...")

        # 1. Filter: Only Valid Attempts (Spatial Overlap)
        attempts = df.filter(pl.col("spatial_overlap") == True)

        # 2. Define Success
        attempts = attempts.with_columns(
            (pl.col("left_smell") & (~pl.col("right_smell"))).alias("is_fixed")
        )

        # 3. Group by Rule Name
        return (
            attempts.group_by("rule_name")
            .agg([
                pl.len().alias("Total_Occurrences"),
                pl.col("is_fixed").sum().alias("Fixed_Count")
            ])
            .with_columns(
                (pl.col("Fixed_Count") / pl.col("Total_Occurrences") * 100).round(2).alias("Fix_Rate")
            )
            .sort("Fix_Rate", descending=True)
        )