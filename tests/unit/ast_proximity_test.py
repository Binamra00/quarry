import pytest
import polars as pl
import json
from pathlib import Path
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


@pytest.fixture
def mock_paths(tmp_path):
    return {
        "ref": tmp_path / "refactorings.jsonl",
        "pmd": tmp_path / "pmd_history.jsonl",
        "lin": tmp_path / "lineage.jsonl"
    }


def create_mock_data(paths, scenario):
    """
    Creates Schema-Compliant Mock Data.
    Crucial: Must include ALL fields required by DTOLoader schemas.
    """

    # 1. Lineage
    with open(paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "child_sha", "parent_sha": "parent_sha"}) + "\n")

    # 2. Refactorings (Strict Schema Compliance)
    ref_record = {
        "repository": "repo",
        "sha1": "child_sha",
        "refactorings": [{
            "type": "Extract Method",
            "description": "desc",
            "leftSideLocations": [{
                "filePath": "src/Target.java",
                "startLine": 10, "endLine": 20
            }],
            "rightSideLocations": []
        }]
    }
    with open(paths["ref"], "w") as f:
        f.write(json.dumps(ref_record) + "\n")

    # 3. PMD History (Strict Schema Compliance)
    pmd_records = []

    # PARENT COMMIT STATE
    parent_violations = []
    if scenario in ["Fixed", "Persistent"]:
        parent_violations.append({
            "filename": "src/Target.java",
            "rule": "GodClass",
            "priority": 1,
            "beginline": 5, "endline": 100,
            "description": "Too complex"
        })
    pmd_records.append({
        "sha": "parent_sha",
        "status": "success",
        "violations": parent_violations
    })

    # CHILD COMMIT STATE
    child_violations = []
    if scenario == "Persistent":
        child_violations.append({
            "filename": "src/Target.java",
            "rule": "GodClass",
            "priority": 1,
            "beginline": 5, "endline": 100,
            "description": "Still complex"
        })
    pmd_records.append({
        "sha": "child_sha",
        "status": "success",
        "violations": child_violations
    })

    with open(paths["pmd"], "w") as f:
        for r in pmd_records:
            f.write(json.dumps(r) + "\n")


def test_causality_fixed(mock_paths):
    """Refactoring Removed the Smell (Parent=Yes, Child=No)"""
    create_mock_data(mock_paths, "Fixed")

    ctx = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    df = ASTProximityStrategy().execute(ctx, None).collect()

    assert len(df) == 1
    assert df["causality_type"][0] == "Fixed"
    assert df["score_AST_Proximity"][0] == 1.0


def test_causality_persistent(mock_paths):
    """Refactoring Failed to Remove Smell (Parent=Yes, Child=Yes)"""
    create_mock_data(mock_paths, "Persistent")

    ctx = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    df = ASTProximityStrategy().execute(ctx, None).collect()

    assert len(df) == 1
    assert df["causality_type"][0] == "Persistent"
    assert df["score_AST_Proximity"][0] == 1.0


def test_causality_none(mock_paths):
    """No Smell in Parent or Child (Unrelated Refactoring)"""
    create_mock_data(mock_paths, "None")

    ctx = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    df = ASTProximityStrategy().execute(ctx, None).collect()

    assert len(df) == 1
    assert df["causality_type"][0] == "None"
    assert df["score_AST_Proximity"][0] == 0.0


def test_path_normalization_windows_absolute(mock_paths):
    """
    Scenario: PMD reports absolute Windows paths (messy),
              RefactoringMiner reports relative paths (clean).
    Goal: Verify Phase 2 Regex successfully normalizes and matches them.
    """
    # 1. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "child_sha", "parent_sha": "parent_sha"}) + "\n")

    # 2. Refactoring (Clean Relative Path)
    ref_record = {
        "repository": "repo",
        "sha1": "child_sha",
        "refactorings": [{
            "type": "Rename Class",
            "description": "rename",
            "leftSideLocations": [{
                "filePath": "src/com/legacy/MessyPath.java",  # <--- CLEAN
                "startLine": 10, "endLine": 20
            }],
            "rightSideLocations": []
        }]
    }
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(ref_record) + "\n")

    # 3. PMD (Messy Absolute Windows Path)
    # This simulates the environment Copilot warned about
    pmd_record = {
        "sha": "child_sha",
        "status": "success",
        "violations": [{
            # <--- MESSY: Phase 2 Regex must fix this to "src/com/legacy/MessyPath.java"
            "filename": r"E:\Jenkins\Workspace\jobs\pipeline\repos\toy_project\src\com\legacy\MessyPath.java",
            "rule": "ComplexClass",
            "priority": 1,
            "beginline": 10, "endline": 20,
            "description": "Too complex"
        }]
    }
    with open(mock_paths["pmd"], "w") as f:
        f.write(json.dumps(pmd_record) + "\n")

    # Execute
    ctx = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    # Run Strategy
    df = ASTProximityStrategy().execute(ctx, None).collect()

    # Assertions
    assert len(df) == 1
    # If Regex fails, this will be 0.0 because paths won't match
    assert df["score_AST_Proximity"][0] == 1.0
    # Verify the path was normalized in the output
    assert df["file_path"][0] == "src/com/legacy/MessyPath.java"