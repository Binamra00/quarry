import polars as pl
from typing import Dict, Optional, Any
from pipeline.heuristics.strategies.i_strategy import IHeuristicStrategy


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

        # 2. Load Data
        refactorings = self._load_refactorings(ref_path)
        pmd = self._load_pmd(pmd_path)
        lineage = self._load_lineage(lineage_path)

        # 3. Attach Parent SHA to Refactorings (The Time Machine)
        # Refactorings now have [commit_sha, parent_sha, file_path, ...]
        refactorings = refactorings.join(lineage, on="commit_sha", how="left")

        # 4. Perform the Dual-Lookup (Past + Present)

        final_df = (
            refactorings
            # JOIN A: Check Current Commit (Did the smell survive?)
            # Match: Refactoring(commit_sha) == PMD(commit_sha)
            .join(
                pmd.rename({"rule_name": "rule_current"}),
                on=["commit_sha", "file_path"],
                how="left"
            )
            # JOIN B: Check Parent Commit (Did the smell exist before?)
            # Match: Refactoring(parent_sha) == PMD(commit_sha)
            # Note: The PMD dataset is indexed by 'commit_sha'. We match our 'parent_sha' to it.
            .join(
                pmd.rename({"commit_sha": "parent_sha", "rule_name": "rule_parent"}),
                left_on=["parent_sha", "file_path"],
                right_on=["parent_sha", "file_path"],
                how="left"
            )
            # 5. Scoring Logic
            .with_columns(
                # Score is 1.0 if we find a smell in EITHER the past or present
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
            # 7. Coalesce: Pick the best rule name to display (prioritize Parent/Fixed for analysis)
            .with_columns(
                pl.coalesce(["rule_parent", "rule_current"]).alias("rule_name")
            )
        )

        return final_df

    # --- Loaders ---

    def _load_lineage(self, path: str) -> pl.LazyFrame:
        """Loads the pre-mined parentage graph."""
        return pl.scan_ndjson(path)

    def _load_refactorings(self, path: str) -> pl.LazyFrame:
        """Loads and normalizes RefactoringMiner output."""
        return (
            pl.scan_ndjson(path, infer_schema_length=10000)
            .rename({"sha1": "commit_sha"})
            .explode("refactorings")
            .unnest("refactorings")
            .with_columns([
                # We focus on the source file for smell correlation
                pl.col("leftSideLocations").list.first().struct.field("filePath").alias("file_path"),
                pl.col("type").alias("refactoring_type"),
                pl.col("description")
            ])
            .drop(["leftSideLocations", "rightSideLocations"])
        )

    def _load_pmd(self, path: str) -> pl.LazyFrame:
        """
        Loads PMD history with robust nested handling.
        Uses eager loading to ensure correct schema inference for sparse data.
        """
        df_eager = pl.read_ndjson(path)
        return (
            df_eager.lazy()
            .rename({"sha": "commit_sha"})
            .explode("violations")
            .unnest("violations")
            .rename({"violations": "smells"})
            .explode("smells")
            .unnest("smells")
            .with_columns(
                pl.col("filename")
                .str.replace_all(r"\\", "/")
                .str.replace(r"^.*/repos/[^/]+/", "")
                .alias("file_path")
            )
            .rename({"rule": "rule_name"})
            .select(["commit_sha", "file_path", "rule_name"])
        )