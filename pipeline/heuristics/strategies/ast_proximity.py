import polars as pl
from typing import Dict, Optional, Any
from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class ASTProximityStrategy(IHeuristicStrategy):
    """
    Heuristic B: AST Spatial Proximity (Temporal & Spatial).

    Checks two states to establish causality:
    1. PRE-CONDITION (Parent Commit): Did the smell exist before the refactoring? (Fixed Smells)
    2. POST-CONDITION (Current Commit): Does the smell persist after? (Persistent Smells)
    """

    MATCH_SCORE = 1.0
    NO_MATCH_SCORE = 0.0

    @property
    def name(self) -> str:
        return "AST_Proximity"

    @property
    def description(self) -> str:
        return (
            "Heuristic B: AST Spatial Proximity (Temporal & Spatial). "
            "Checks whether a code smell existed before a refactoring and/or "
            "persists after it, using AST-based spatial and temporal proximity."
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

        # 2. Attach Parent SHA
        refactorings = refactorings.join(lineage, on="commit_sha", how="left")

        # 3. Dual-Lookup (Past + Present)
        final_df = (
            refactorings
            # JOIN A: Check Current Commit (Persistent?)
            # We rename ALL PMD columns to suffix '_current'
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
            # We rename ALL PMD columns to suffix '_parent'
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
            # 4. Scoring Logic
            .with_columns(
                pl.when(
                    pl.col("rule_current").is_not_null() | pl.col("rule_parent").is_not_null()
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
            # 6. Coalesce Logic: Merge Parent/Current columns into a single final view
            # Priority: If 'Fixed', show Parent data (where the smell WAS).
            #           If 'Persistent', show Current data (where the smell IS).
            .with_columns([
                pl.coalesce(["rule_current", "rule_parent"]).alias("rule_name"),
                pl.coalesce(["start_current", "start_parent"]).alias("start_line"),
                pl.coalesce(["end_current", "end_parent"]).alias("end_line"),
                pl.coalesce(["priority_current", "priority_parent"]).alias("priority"),
                pl.coalesce(["message_current", "message_parent"]).alias("message")
            ])
        )

        return final_df