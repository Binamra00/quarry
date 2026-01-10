import polars as pl
from pipeline.heuristics.i_heuristics import IHeuristicStrategy


class ASTProximityStrategy(IHeuristicStrategy):
    """
    Heuristic B: AST-Based Spatial Proximity.

    Logic:
    Verifies if the Refactoring actually 'touched' the code that was smelling.
    This filters out 'Coincidental Refactorings' (e.g., a huge commit where
    someone fixed a bug in Method A but the smell was in Method B).
    """

    @property
    def name(self) -> str:
        return "AST_Proximity"

    @property
    def description(self) -> str:
        return "Binary validation (1.0/0.0) based on line-range intersection."

    def calculate(self, joined_frame: pl.LazyFrame) -> pl.LazyFrame:
        """
        Applies the Interval Intersection Formula.

        Expected Schema from Join:
        - start_line, end_line (from Smell)
        - start_line_ref, end_line_ref (from Refactoring)
        """
        return joined_frame.with_columns(
            # 1. Calculate Overlap Boundaries
            pl.max_horizontal("start_line", "start_line_ref").alias("overlap_start"),
            pl.min_horizontal("end_line", "end_line_ref").alias("overlap_end")
        ).with_columns(
            # 2. Calculate Intersection Length (Zero if negative)
            (pl.col("overlap_end") - pl.col("overlap_start") + 1)
            .clip(lower_bound=0)
            .alias("intersection_len")
        ).with_columns(
            # 3. Final Score: 1.0 if overlap exists, else 0.0
            pl.when(pl.col("intersection_len") > 0)
            .then(pl.lit(1.0))
            .otherwise(pl.lit(0.0))
            .alias(f"score_{self.name}")
        ).drop(
            # Cleanup intermediate columns to save space
            ["overlap_start", "overlap_end", "intersection_len"]
        )