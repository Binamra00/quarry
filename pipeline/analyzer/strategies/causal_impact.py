# pipeline/analyzer/strategies/causal_impact.py
import polars as pl
from typing import Dict, Any
from ..contracts import IAnalyzerStrategy, IRelevanceSpec


class CausalImpactStrategy(IAnalyzerStrategy):
    def name(self) -> str:
        return "causal_impact"

    def execute(self, df: pl.LazyFrame, context: Dict[str, Any]) -> pl.LazyFrame:
        spec: IRelevanceSpec = context.get("relevance_spec")

        # 1. Expand Spec
        valid_pairs = []
        for ref_type, rules in spec.rules.items():
            for rule in rules:
                valid_pairs.append({"refactoring_type": ref_type, "rule": rule})
        spec_df = pl.DataFrame(valid_pairs).lazy()

        # 2. Filter (Using CLEAN names: 'refactoring_type', 'rule')
        joined_df = df.join(
            spec_df,
            on=["refactoring_type", "rule"],
            how="inner"
        )

        # 3. Calculate Delta (Using CLEAN names: 'score_before', 'score_after')
        calculated_df = joined_df.with_columns(
            (pl.col("score_before") - pl.col("score_after")).alias("delta")
        )

        # 4. Classify
        final_df = calculated_df.with_columns(
            pl.when(pl.col("delta") > 0).then(pl.lit("Confirmed Fix"))
            .when(pl.col("delta") <= 0).then(pl.lit("Ineffective Refactoring"))
            .otherwise(pl.lit("Unknown"))
            .alias("causal_verdict")
        )

        return final_df