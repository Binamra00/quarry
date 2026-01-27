# analysis/repository.py
import polars as pl
import os
import logging

# We use absolute imports because you are running this as a module
from analysis.config import Config

logger = logging.getLogger(__name__)


class GroundTruthRepository:
    """
    Acts as the Single Source of Truth.
    Responsible for loading Parquet, handling missing columns, and
    returning a clean, normalized DataFrame.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load_data(self) -> pl.DataFrame:
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"❌ Input file not found: {self.file_path}")

        logger.info(f"📂 Loading Ground Truth from: {self.file_path}")
        df = pl.read_parquet(self.file_path)

        # Normalize Schema (Fixing the column name drift)
        df = self._normalize_schema(df)

        logger.info(f"✅ Data Loaded Successfully: {len(df):,} rows.")
        return df

    def _normalize_schema(self, df: pl.DataFrame) -> pl.DataFrame:
        """Ensures consistent column names for analysis."""
        # 1. Fix Spatial Overlap Column
        # Your pipeline produced 'score_AST_Proximity', but analysis needs 'spatial_overlap'
        if "spatial_overlap" not in df.columns:
            if "score_AST_Proximity" in df.columns:
                logger.info("🔧 Normalizing: score_AST_Proximity -> spatial_overlap")
                # 1.0 means True, 0.0 means False
                df = df.with_columns(
                    (pl.col("score_AST_Proximity") == 1.0).alias("spatial_overlap")
                )
            else:
                logger.warning("⚠️ No overlap column found. Defaulting to True (Unsafe).")
                df = df.with_columns(pl.lit(True).alias("spatial_overlap"))

        # 2. Ensure Boolean Types for Logic
        # We cast them explicitly to avoid TypeErrors later
        return df.with_columns([
            pl.col("spatial_overlap").cast(pl.Boolean),
            pl.col("left_smell").cast(pl.Boolean),
            pl.col("right_smell").cast(pl.Boolean)
        ])