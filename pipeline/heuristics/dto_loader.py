import polars as pl


class HeuristicSchemas:
    """
    Defines the strict schema (DTO) for input data.
    """

    # 1. RefactoringMiner Structure (Fixed for Right-Side detection)
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

    # 2. PMD Structure (Double-Nested)
    PMD_SCHEMA = {
        "sha": pl.Utf8,
        "status": pl.Utf8,
        "violations": pl.List(
            pl.Struct({
                "filename": pl.Utf8,
                "violations": pl.List(
                    pl.Struct({
                        "rule": pl.Utf8,
                        "priority": pl.Int64,
                        "beginline": pl.Int64,
                        "endline": pl.Int64,
                        "description": pl.Utf8
                    })
                )
            })
        )
    }

    LINEAGE_SCHEMA = {"commit_sha": pl.Utf8, "parent_sha": pl.Utf8}


class DTOLoader:
    @staticmethod
    def load_refactorings(file_path: str) -> pl.LazyFrame:
        return (
            pl.scan_ndjson(file_path, schema=HeuristicSchemas.REFM_SCHEMA)
            .rename({"sha1": "commit_sha"})
            .explode("refactorings")
            .unnest("refactorings")
            .with_columns([
                # 1. Left Side Path (parent / Old Location)
                pl.col("leftSideLocations").list.first().struct.field("filePath")
                .str.replace_all(r"\\", "/")
                .str.replace(r"^.*?(src|source|lib)/", r"$1/", literal=False)
                .alias("left_side_path"),

                # 2. Right Side Path (current / New Location)
                pl.col("rightSideLocations").list.first().struct.field("filePath")
                .str.replace_all(r"\\", "/")
                .str.replace(r"^.*?(src|source|lib)/", r"$1/", literal=False)
                .alias("right_side_path"),

                # PARENT Coordinates
                pl.col("leftSideLocations").list.first().struct.field("startLine").alias("start_line_ref_left"),
                pl.col("leftSideLocations").list.first().struct.field("endLine").alias("end_line_ref_left"),

                # CHILD Coordinates
                pl.col("rightSideLocations").list.first().struct.field("startLine").alias("start_line_ref_right"),
                pl.col("rightSideLocations").list.first().struct.field("endLine").alias("end_line_ref_right"),

                # Metadata
                pl.col("type").alias("refactoring_type"),
                pl.col("description")
            ])
            # [FIX]: Robust File Path Definition (Coalesce Right -> Left)
            # This is the SINGLE source of truth for file_path now.
            # IMPORTANT: When right_side_path is null/empty (e.g., 'Remove Method'),
            # we fall back to left_side_path to ensure the row is not dropped.
            .with_columns([
                pl.coalesce([pl.col("right_side_path"), pl.col("left_side_path")]).alias("file_path")
            ])
            .filter(pl.col("file_path").is_not_null())
            .drop(["leftSideLocations", "rightSideLocations"])
        )

    @staticmethod
    def load_pmd(file_path: str) -> pl.LazyFrame:
        return (
            pl.scan_ndjson(file_path, schema=HeuristicSchemas.PMD_SCHEMA)
            .rename({"sha": "commit_sha"})
            .explode("violations")
            .unnest("violations")
            .explode("violations")
            .unnest("violations")
            .with_columns(
                pl.col("filename")
                .str.replace_all(r"\\", "/")
                .str.replace(r"^.*?(src|source|lib)/", r"$1/", literal=False)
                .alias("file_path")
            )
            .filter(pl.col("file_path").is_not_null())
            .rename({
                "rule": "rule_name", "beginline": "start_line",
                "endline": "end_line", "description": "message"
            })
            .select(["commit_sha", "file_path", "rule_name", "priority", "start_line", "end_line", "message"])
        )

    @staticmethod
    def load_lineage(file_path: str) -> pl.LazyFrame:
        return pl.scan_ndjson(file_path, schema=HeuristicSchemas.LINEAGE_SCHEMA)