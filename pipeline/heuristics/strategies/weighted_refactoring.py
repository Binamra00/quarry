import polars as pl
from typing import Dict, Any, Optional
from pipeline.heuristics.i_heuristics import IHeuristicStrategy
from pipeline.heuristics.dto_loader import DTOLoader


class WeightedRefactoringStrategy(IHeuristicStrategy):
    """
    Heuristic A: Complexity Analysis (Weighted Refactoring).

    Configuration:
        Reads 'complexity_rules' from the injected 'heuristic_seeds.json'.
        This allows weights to be tuned without changing source code.

    Logic:
        1. Loads refactorings.
        2. Joins with the configured weight map.
        3. Escalates 'Renames' to High Impact if API visibility is detected.
    """

    @property
    def name(self) -> str:
        return "Complexity"

    @property
    def description(self) -> str:
        return "Configurable complexity scoring based on architectural impact and API visibility."

    def execute(self, context: Dict[str, Any], data: Optional[pl.LazyFrame]) -> pl.LazyFrame:
        ref_path = context.get("refactorings_path")

        # [NEW] Retrieve Configuration from Context
        # The Engine injected this from heuristic_seeds.json
        seeds = context.get("heuristic_seeds", {})
        rules_map = seeds.get("complexity_rules", {})

        if not ref_path:
            raise ValueError("WeightedRefactoringStrategy requires 'refactorings_path' in context.")

        # Graceful degradation if config is missing
        if not rules_map:
            print("    ⚠️ Warning: No 'complexity_rules' found in heuristic_seeds.json. Using default weights (0.1).")

        # 1. Load Data
        if data is None:
            refactorings = DTOLoader.load_refactorings(ref_path)
        else:
            refactorings = data

        # 2. Create Lookup DataFrame from JSON Config
        # JSON Format: "RuleName": [Score, Category]
        # We need to unzip the dictionary into lists for Polars
        keys = list(rules_map.keys())
        scores = [v[0] for v in rules_map.values()]
        cats = [v[1] for v in rules_map.values()]

        weights_df = pl.DataFrame({
            "refactoring_type": keys,
            "base_score": scores,
            "base_category": cats
        }).lazy()

        # 3. Perform Join & Apply Logic
        enriched_data = (
            refactorings
            .join(weights_df, on="refactoring_type", how="left")

            # Safety Defaults (Handles unknown types not in JSON)
            .with_columns([
                pl.col("base_score").fill_null(0.1),
                pl.col("base_category").fill_null("Unknown")
            ])

            # === Flag Escalation (Traceability Step) ===
            .with_columns(
                pl.when(
                    # Precision: Only escalate explicit Method Renames
                    (pl.col("refactoring_type") == "Rename Method") &
                    # Nuance: Check for API visibility keywords in description
                    (pl.col("description").str.contains(r"\b(public|protected)\b"))
                )
                .then(True)
                .otherwise(False)
                .alias("is_escalated")
            )

            # === Record Escalation Reason ===
            .with_columns(
                pl.when(pl.col("is_escalated"))
                .then(pl.lit("public_api_rename"))
                .otherwise(pl.lit(None))
                .alias("escalation_reason")
            )

            # === Calculate Effective Score ===
            .with_columns(
                pl.when(pl.col("is_escalated"))
                .then(1.0)
                .otherwise(pl.col("base_score"))
                .alias("complexity_score")
            )

            # === Calculate Effective Category ===
            .with_columns(
                pl.when(pl.col("is_escalated"))
                .then(pl.lit("High_API_Escalated"))
                .otherwise(pl.col("base_category"))
                .alias("impact_category")
            )
        )

        return enriched_data