# pipeline/analyzer/loader.py
import polars as pl
from pathlib import Path

class AnalyzerDataLoader:
    """
    Responsible for loading Ground Truth data and enforcing a strict schema.
    Acts as an Adapter between the raw Parquet output of Phase 4 and the
    clean expectations of Phase 5.
    """

    @staticmethod
    def load_ground_truth(file_path: Path) -> pl.LazyFrame:
        """
        Loads the ground truth parquet and normalizes column names.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Ground Truth file not found: {file_path}")

        # 1. Load Raw Data
        lf = pl.scan_parquet(file_path)

        # 2. Normalize Schema (The Adapter Layer)
        # We map the "Actual" columns (from Phase 4) to "Expected" columns (for Phase 5)
        lf_normalized = lf.rename({
            "rule_name": "rule",                    # Standardize 'rule'
            "previous_pmd_score": "score_before",   # Standardize 'score_before'
            "current_pmd_score": "score_after",     # Standardize 'score_after'
            "sha1": "commit_sha"                    # Ensure consistency
        })

        # 3. Type Enforcement (Defensive Coding)
        # Ensure scores are integers and nulls are handled (fill with 0 for calculation safety)
        lf_clean = lf_normalized.with_columns([
            pl.col("score_before").fill_null(0).cast(pl.Int32),
            pl.col("score_after").fill_null(0).cast(pl.Int32),
            pl.col("rule").cast(pl.Utf8),
            pl.col("refactoring_type").cast(pl.Utf8)
        ])

        return lf_clean