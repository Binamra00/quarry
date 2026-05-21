import polars as pl
from typing import Dict, Any, Optional
from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class ASTProximityStrategy(IHeuristicStrategy):
    """
    Implementation of AST Spatial Proximity Heuristic.

    [UPGRADE]: Includes 'left_smell' and 'right_smell' booleans for explicit state tracking.
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

        # 1. Load Data (Preserve Chain of Responsibility)
        # [GOOD PIPE FIX]: If data is passed from Heuristic A, use it. Don't reload from disk.
        if data is None:
            refactorings = DTOLoader.load_refactorings(ref_path)
        else:
            refactorings = data
        pmd = DTOLoader.load_pmd(pmd_path)
        # [FIX] Explicit Projection & Aliasing (Standard ETL Pattern)
        # We strictly select only the join keys we need to avoid polluting the namespace.
        lineage = DTOLoader.load_lineage(lineage_path).select([
            pl.col("commit_sha"),
            pl.col("parent_sha").alias("ref_parent_sha")
        ])

        # 2. Attach Parent SHA (Explicit Rename to avoid ambiguity)
        # We rename 'parent_sha' to 'ref_parent_sha' to distinguish it from PMD columns
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
                    "message": "message_current",
                    "pmd_complexity_score": "score_current"
                }),
                left_on=["commit_sha", "right_side_path"],  # Explicitly use Right (Current) Path
                right_on=["commit_sha", "file_path"],
                how="left"
            )
            # JOIN B: Check Parent Commit (Fixed?)
            .join(
                pmd.rename({
                    "commit_sha": "pmd_parent_sha",
                    "rule_name": "rule_parent",
                    "start_line": "start_parent",
                    "end_line": "end_parent",
                    "priority": "priority_parent",
                    "message": "message_parent",
                    "pmd_complexity_score": "score_parent"
                }),
                left_on=["ref_parent_sha", "left_side_path"],  # Explicitly use Left (Parent) Path
                right_on=["pmd_parent_sha", "file_path"],
                how="left"
            )

            # 4. [NEW] Calculate Spatial Booleans FIRST
            # This is the raw truth: Is the smell fully contained within the refactoring bounds?
            # Boundary Logic: INCLUSIVE [start, end].
            # Design Decision: We enforce STRICT CONTAINMENT.
            # Partial overlaps (e.g., smell 15-25 vs refactoring 10-20) are ignored to ensure
            # high statistical confidence that the refactoring interacts with the smell.
            .with_columns([
                (
                        (pl.col("rule_parent").is_not_null()) &
                        (pl.col("start_parent") >= pl.col("start_line_ref_left")) &
                        (pl.col("end_parent") <= pl.col("end_line_ref_left"))
                ).fill_null(False).alias("left_smell"),  # Was it there before? (Parent)

                (
                        (pl.col("rule_current").is_not_null()) &
                        (pl.col("start_current") >= pl.col("start_line_ref_right")) &
                        (pl.col("end_current") <= pl.col("end_line_ref_right"))
                ).fill_null(False).alias("right_smell")  # Is it there now? (Current)
            ])

            # 5. Score & Causality (Derived from Booleans & Revealed Preference)
            .with_columns([
                # Score: 1.0 if it overlaps on EITHER side
                pl.when(pl.col("left_smell") | pl.col("right_smell"))
                .then(self.MATCH_SCORE)
                .otherwise(self.NO_MATCH_SCORE)
                .alias("score_AST_Proximity"),

                # Causality: Explicit Logic
                pl.when(
                    # Case A: Complete Fix (Smell vanished)
                    pl.col("left_smell") & ~pl.col("right_smell")
                )
                .then(pl.lit("Fixed"))

                # [NEW] Case B: Amelioration (Smell exists, but score dropped)
                # e.g. Complexity went from 15 -> 7
                .when(
                    pl.col("left_smell") & pl.col("right_smell") &
                    (pl.col("score_current") < pl.col("score_parent"))
                )
                .then(pl.lit("Ameliorated"))

                # Case C: Persistence (Smell exists, score same or worse)
                .when(pl.col("left_smell") & pl.col("right_smell"))
                .then(pl.lit("Persistent"))

                # Case D: Regression (New smell appeared)
                .when(~pl.col("left_smell") & pl.col("right_smell"))
                .then(pl.lit("Introduction"))

                .otherwise(pl.lit("None"))
                .alias("causality_type")
            ])

            # 6. Coalesce Logic: Unified View
            .with_columns([
                pl.coalesce(["rule_current", "rule_parent"]).alias("rule_name"),
                pl.coalesce(["start_current", "start_parent"]).alias("pmd_smell_start_line"),
                pl.coalesce(["end_current", "end_parent"]).alias("pmd_smell_end_line"),
                pl.coalesce(["priority_current", "priority_parent"]).alias("pmd_priority_score"),
                pl.coalesce(["message_current", "message_parent"]).alias("message"),
                # [NEW] Aliases for Paper/Plotting
                pl.col("score_current").alias("current_pmd_score"),
                pl.col("score_parent").alias("previous_pmd_score"),
                pl.col("commit_sha").alias("sha1")
            ])
        )

        # 7. Final Projection (Defensive Drop)
        # [REVERTED STRATEGY]: We use 'exclude' instead of 'select'.
        # Why?
        # 1. Tests need internal cols like 'score_AST_Proximity' and 'left_smell'.
        # 2. Pipeline needs to preserve columns from previous heuristics (Good Pipe).
        cols_to_remove = {
            "rule_current", "start_current", "end_current", "priority_current", "message_current",
            "rule_parent", "start_parent", "end_parent", "priority_parent", "message_parent",
            "ref_parent_sha", "pmd_parent_sha",
            "repository", "type", "file_path",
            # Remove raw score cols since we aliased them in Step 6
            "score_current", "score_parent"
        }

        return final_df.select(pl.exclude(cols_to_remove))
