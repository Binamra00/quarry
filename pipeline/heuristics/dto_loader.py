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


class DTOLoader:
    """
    The Data Access Layer (DAL).
    Responsible for creating flattened 'LazyFrames' ready for joining.
    """

    @staticmethod
    def load_refactorings(file_path: Path) -> pl.LazyFrame:
        """
        Loads and flattens Refactorings.
        """
        # [FIX] Enforce schema to handle empty lists in the first few rows
        return (
            pl.scan_ndjson(str(file_path), schema=HeuristicSchemas.REFM_SCHEMA)
            .explode("refactorings")
            .unnest("refactorings")
            .rename({"sha1": "commit_sha"})
            # Extract the first source location for overlap calculation
            .with_columns(
                pl.col("leftSideLocations").list.first().alias("source_loc")
            )
            .unnest("source_loc")
            .select([
                pl.col("commit_sha"),
                pl.col("type").alias("refactoring_type"),
                pl.col("filePath").alias("file_path"),
                pl.col("startLine").alias("start_line"),
                pl.col("endLine").alias("end_line"),
                pl.col("description")
            ])
            # Filter out nulls (commits with no refactorings)
            .filter(pl.col("refactoring_type").is_not_null())
        )

    @staticmethod
    def load_smells(file_path: Path) -> pl.LazyFrame:
        """
        Loads and flattens PMD Smells.
        """
        # [FIX] Enforce schema so 'unnest' knows 'rule' exists even if violations=[]
        return (
            pl.scan_ndjson(str(file_path), schema=HeuristicSchemas.PMD_SCHEMA)
            .filter(pl.col("status") == "success")  # Ignore failed runs
            .explode("violations")
            .unnest("violations")
            .rename({
                "sha": "commit_sha",
                "rule": "rule_name",
                "beginline": "start_line",
                "endline": "end_line",
                "description": "message"
            })
            .with_columns(
                # CLEANUP: Extract relative path from absolute path
                # Regex logic: Keep everything after the last 'src' or similar structure
                pl.col("filename")
                .str.replace(r".*src", "src", literal=False)
                .str.replace_all(r"\\", "/")  # Normalize Windows slashes
                .alias("file_path")
            )
            .select([
                "commit_sha",
                "file_path",
                "rule_name",
                "priority",
                "start_line",
                "end_line",
                "message"
            ])
        )