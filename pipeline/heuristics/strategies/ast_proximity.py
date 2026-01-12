import polars as pl
from typing import Dict, Any, Optional
from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class ASTProximityStrategy(IHeuristicStrategy):
    """
    Implementation of AST Spatial Proximity Heuristic.
    Returns ALL potential candidates (Score 1.0 and 0.0) to avoid ML bias.
    """

    MATCH_SCORE = 1.0
    NO_MATCH_SCORE = 0.0

    @property
    def name(self) -> str:
        return "AST_Proximity"

    @property
    def description(self) -> str:
        return (
            "Measures spatial proximity between refactoring locations and static analysis "
            "findings in the AST across current and parent commits."
        )

    def execute(self, context: Dict[str, Any], data: Optional[pl.LazyFrame]) -> pl.LazyFrame:
        ref_path = context.get("refactorings_path")
        pmd_path = context.get("pmd_path")
        lineage_path = context.get("lineage_path")

        if not ref_path or not pmd_path or not lineage_path:
            raise ValueError("AST_Proximity requires refactorings, pmd, and lineage paths.")

        # 1. Load Data
        refactorings = DTOLoader.load_refactorings(ref_path)
        pmd = DTOLoader.load_pmd(pmd_path)
        lineage = DTOLoader.load_lineage(lineage_path)

        # 2. Attach Parent SHA (Crucial for causality)
        refactorings = refactorings.join(lineage, on="commit_sha", how="left")

        # 3. Dual-Lookup (Past + Present)
        final_df = (
            refactorings
            # JOIN A: Check Current Commit (Persistent?)
            .join(
                pmd.rename({
                    "rule_name": "rule_current",
                    "start_line": "start_current",
                    "end_line": "end_current",
                    "priority": "priority_current",
                    "message": "message_current"
                }),
                on=["commit_sha", "file_path"],
                how="left"
            )
            # JOIN B: Check Parent Commit (Fixed?)
            .join(
                pmd.rename({
                    "commit_sha": "parent_sha",
                    "rule_name": "rule_parent",
                    "start_line": "start_parent",
                    "end_line": "end_parent",
                    "priority": "priority_parent",
                    "message": "message_parent"
                }),
                left_on=["parent_sha", "file_path"],
                right_on=["parent_sha", "file_path"],
                how="left"
            )

            # 4. Coordinate-Aware Spatial Scoring
            # We determine if the smell is INSIDE the refactoring bounds.
            .with_columns(
                pl.when(
                    # Scenario A: Persistent (Check CHILD smell vs CHILD refactoring)
                    (pl.col("rule_current").is_not_null() &
                     (pl.col("start_current") >= pl.col("start_line_ref_right")) &
                     (pl.col("end_current") <= pl.col("end_line_ref_right"))) |

                    # Scenario B: Fixed (Check PARENT smell vs PARENT refactoring)
                    (pl.col("rule_parent").is_not_null() &
                     (pl.col("start_parent") >= pl.col("start_line_ref_left")) &
                     (pl.col("end_parent") <= pl.col("end_line_ref_left")))
                )
                .then(self.MATCH_SCORE)
                .otherwise(self.NO_MATCH_SCORE)
                .alias("score_AST_Proximity")
            )

            # 5. Metadata: Causality Type
            .with_columns(
                pl.when(pl.col("rule_current").is_null() & pl.col("rule_parent").is_not_null())
                .then(pl.lit("Fixed"))
                .when(pl.col("rule_current").is_not_null())
                .then(pl.lit("Persistent"))
                .otherwise(pl.lit("None"))
                .alias("causality_type")
            )

            # 6. Coalesce Logic: Unified View
            .with_columns([
                pl.coalesce(["rule_current", "rule_parent"]).alias("rule_name"),
                pl.coalesce(["start_current", "start_parent"]).alias("start_line"),
                pl.coalesce(["end_current", "end_parent"]).alias("end_line"),
                pl.coalesce(["priority_current", "priority_parent"]).alias("priority"),
                pl.coalesce(["message_current", "message_parent"]).alias("message")
            ])

            # 7. Final Selection: REMOVED .filter() to include all candidates for ML
            .select([
                "commit_sha",
                "file_path",
                "rule_name",
                "priority",
                "start_line",
                "end_line",
                "start_line_ref_left",
                "start_line_ref_right",
                "refactoring_type",
                "message",
                "score_AST_Proximity",
                "causality_type"
            ])
        )

        return final_df