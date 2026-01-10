import polars as pl
from typing import Dict, Optional, Any
from pipeline.heuristics.strategies.i_strategy import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class ASTProximityStrategy(IHeuristicStrategy):
    """
    Heuristic B: AST Spatial Proximity (Temporal & Spatial).

    Checks two states to establish causality:
    1. PRE-CONDITION (Parent Commit): Did the smell exist before the refactoring? (Fixed Smells)
    2. POST-CONDITION (Current Commit): Does the smell persist after? (Persistent Smells)
    """

    @property
    def name(self) -> str:
        return "AST_Proximity"

    def execute(self, context: Dict[str, Any], data: Optional[pl.LazyFrame]) -> pl.LazyFrame:
        # 1. Extract paths from context
        ref_path = context.get("refactorings_path")
        pmd_path = context.get("pmd_path")
        lineage_path = context.get("lineage_path")

        if not ref_path or not pmd_path or not lineage_path:
            raise ValueError("AST_Proximity requires refactorings, pmd, and lineage paths.")

        # 2. Load Data via DTO Layer (Centralized Logic & Strict Schema)
        # FIX: Replaced private _load methods with DTOLoader calls
        # This ensures we use scan_ndjson (Lazy) instead of read_ndjson (Eager)
        refactorings = DTOLoader.load_refactorings(ref_path)
        pmd = DTOLoader.load_pmd(pmd_path)
        lineage = DTOLoader.load_lineage(lineage_path)

        # 3. Attach Parent SHA to Refactorings (The Time Machine)
        refactorings = refactorings.join(lineage, on="commit_sha", how="left")

        # 4. Perform the Dual-Lookup (Past + Present)
        final_df = (
            refactorings
            # JOIN A: Check Current Commit (Did the smell survive?)
            .join(
                pmd.rename({"rule_name": "rule_current"}),
                on=["commit_sha", "file_path"],
                how="left"
            )
            # JOIN B: Check Parent Commit (Did the smell exist before?)
            .join(
                pmd.rename({"commit_sha": "parent_sha", "rule_name": "rule_parent"}),
                left_on=["parent_sha", "file_path"],
                right_on=["parent_sha", "file_path"],
                how="left"
            )
            # 5. Scoring Logic
            .with_columns(
                pl.when(
                    pl.col("rule_current").is_not_null() | pl.col("rule_parent").is_not_null()
                )
                .then(1.0)
                .otherwise(0.0)
                .alias("score_AST_Proximity")
            )
            # 6. Metadata: Label the type of causality found
            .with_columns(
                pl.when(pl.col("rule_current").is_null() & pl.col("rule_parent").is_not_null())
                .then(pl.lit("Fixed"))
                .when(pl.col("rule_current").is_not_null())
                .then(pl.lit("Persistent"))
                .otherwise(pl.lit("None"))
                .alias("causality_type")
            )
            # 7. Coalesce Rule Name
            .with_columns(
                pl.coalesce(["rule_parent", "rule_current"]).alias("rule_name")
            )
        )

        return final_df