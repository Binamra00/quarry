import polars as pl
from pathlib import Path

class HeuristicSchemas:
    """
    Defines the strict schema (DTO) for input data.
    These schemas handle the nested JSON structure found in the mining outputs.
    """

    # 1. RefactoringMiner Output Structure
    REFM_SCHEMA = {
        "repository": pl.Utf8,
        "sha1": pl.Utf8,
        "refactorings": pl.List(
            pl.Struct({
                "type": pl.Utf8,
                "description": pl.Utf8,
                "leftSideLocations": pl.List(
                    pl.Struct({
                        "filePath": pl.Utf8,
                        "startLine": pl.Int64,
                        "endLine": pl.Int64
                    })
                ),
                "rightSideLocations": pl.List(
                    pl.Struct({
                        "filePath": pl.Utf8,
                        "startLine": pl.Int64,
                        "endLine": pl.Int64
                    })
                )
            })
        )
    }

    # 2. PMD Output Structure
    PMD_SCHEMA = {
        "sha": pl.Utf8,
        "status": pl.Utf8,
        "violations": pl.List(
            pl.Struct({
                "filename": pl.Utf8,
                "rule": pl.Utf8,
                "priority": pl.Int64,
                "beginline": pl.Int64,
                "endline": pl.Int64,
                "description": pl.Utf8
            })
        )
    }

    # 3. Lineage (Metadata) Structure
    LINEAGE_SCHEMA = {
        "commit_sha": pl.Utf8,
        "parent_sha": pl.Utf8
    }

class DTOLoader:
    """
    Centralized Data Loader.
    Responsible for reading raw JSONL files and returning strongly-typed LazyFrames.
    """

    @staticmethod
    def load_refactorings(file_path: str) -> pl.LazyFrame:
        """
        Loads RefactoringMiner output with strict schema.
        """
        return (
            pl.scan_ndjson(file_path, schema=HeuristicSchemas.REFM_SCHEMA)
            .rename({"sha1": "commit_sha"})
            .explode("refactorings")
            .unnest("refactorings")
            # Flatten LeftSide (Source) locations
            .with_columns([
                pl.col("leftSideLocations").list.first().struct.field("filePath").alias("file_path"),
                pl.col("type").alias("refactoring_type"),
                pl.col("description")
            ])
            .drop(["leftSideLocations", "rightSideLocations"])
        )

    @staticmethod
    def load_pmd(file_path: str) -> pl.LazyFrame:
        """
        Loads PMD output with strict schema.
        Handles empty violation lists gracefully.
        """
        return (
            pl.scan_ndjson(file_path, schema=HeuristicSchemas.PMD_SCHEMA)
            .rename({"sha": "commit_sha"})
            .explode("violations")
            .unnest("violations")
            # [FIX]: Removed invalid .rename({"violations": "smells"}) because
            # 'unnest' consumes the 'violations' column. It is gone now.
            .with_columns(
                pl.col("filename")
                .str.replace_all(r"\\", "/")
                .str.replace(r"^.*/repos/[^/]+/", "")
                .alias("file_path")
            )
            .rename({"rule": "rule_name"})
            .select(["commit_sha", "file_path", "rule_name"])
        )

    @staticmethod
    def load_lineage(file_path: str) -> pl.LazyFrame:
        """
        Loads Commit Lineage with strict schema.
        """
        return pl.scan_ndjson(file_path, schema=HeuristicSchemas.LINEAGE_SCHEMA)