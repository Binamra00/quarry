# analysis/strategies/weapon_matrix.py
import polars as pl
import logging
from .i_analyzer import IAnalyzer

logger = logging.getLogger(__name__)


class WeaponMatrixAnalyzer(IAnalyzer):
    """
    Generates the 'Weapon Matrix' (Refactoring Type x Smell Rule).
    """

    @property
    def name(self) -> str:
        return "table2_weapon_matrix"

    def analyze(self, df: pl.DataFrame) -> pl.DataFrame:
        logger.info("🧠 Running Weapon Matrix Analysis...")

        # 1. Filter: Valid Attempts only
        attempts = df.filter(pl.col("spatial_overlap") == True)

        # 2. Define Success
        attempts = attempts.with_columns(
            (pl.col("left_smell") & (~pl.col("right_smell"))).alias("is_success")
        )

        # 3. Aggregation: Group by BOTH Type and Rule
        return (
            attempts.group_by(["refactoring_type", "rule_name"])
            .agg([
                pl.len().alias("Attempts"),
                pl.col("is_success").sum().alias("Fixed_Count")
            ])
            .with_columns(
                (pl.col("Fixed_Count") / pl.col("Attempts") * 100).round(1).alias("Success_Rate")
            )
            .sort(["Attempts", "Success_Rate"], descending=[True, True])
        )