import pytest
import json
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


@pytest.fixture
def mock_paths(tmp_path):
    """Fixture to provide temporary paths for mock data files."""
    return {
        "ref": tmp_path / "refactorings.jsonl",
        "pmd": tmp_path / "pmd_history.jsonl",
        "lin": tmp_path / "lineage.jsonl"
    }


def create_pmd_7_record(sha, filename, rule, start, end):
    """
    Helper to create PMD 7 double-nested mock records.
    Structure: sha -> list(file_obj -> list(violation_obj))
    """
    return {
        "sha": sha,
        "status": "success",
        "violations": [{
            "filename": filename,
            "violations": [{
                "rule": rule,
                "priority": 3,
                "beginline": start,
                "endline": end,
                "description": "Mock violation"
            }]
        }]
    }


# tests/unit/ast_proximity_test.py

def create_ref_record(sha, filename, type, l_start, l_end, r_start, r_end):
    """
    Helper to create RefactoringMiner mock records with left/right coordinates.
    """
    return {
        "repository": "dummy_repo",  # [FIX] Added required schema field
        "sha1": sha,
        "refactorings": [{
            "type": type,
            "description": f"{type} at {filename}",
            "leftSideLocations": [{"filePath": filename, "startLine": l_start, "endLine": l_end}],
            "rightSideLocations": [{"filePath": filename, "startLine": r_start, "endLine": r_end}]
        }]
    }


# --- 1. Boundary Value Analysis (BVA) Tests ---

def test_spatial_bva_exact_match(mock_paths):
    """BVA: Smell exactly matches refactoring boundaries (Score 1.0)"""
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "child", "parent_sha": "parent"}) + "\n")

    # Refactoring 10-20, Smell 10-20 in Parent (Fixed)
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record("child", "src/A.java", "Extract", 10, 20, 10, 20)) + "\n")
    with open(mock_paths["pmd"], "w") as f:
        f.write(json.dumps(create_pmd_7_record("parent", "src/A.java", "Complexity", 10, 20)) + "\n")

    df = ASTProximityStrategy().execute({
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }, None).collect()

    assert len(df) == 1
    assert df["score_AST_Proximity"][0] == 1.0
    assert df["causality_type"][0] == "Fixed"


def test_spatial_bva_one_line_outside(mock_paths):
    """
    BVA: Smell starts 1 line before refactoring.
    Should return 1 candidate with Score 0.0 (Negative Sample for ML).
    """
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "child", "parent_sha": "parent"}) + "\n")

    # Refactoring 10-20, Smell 9-20 (Parent)
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record("child", "src/A.java", "Extract", 10, 20, 10, 20)) + "\n")
    with open(mock_paths["pmd"], "w") as f:
        f.write(json.dumps(create_pmd_7_record("parent", "src/A.java", "Complexity", 9, 20)) + "\n")

    df = ASTProximityStrategy().execute({
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }, None).collect()

    assert len(df) == 1
    assert df["score_AST_Proximity"][0] == 0.0  # Fails spatial overlap
    assert df["causality_type"][0] == "Fixed"  # Temporal link still exists


# --- 2. Edge Case: Coordinate Shift ---

def test_persistent_with_coordinate_shift(mock_paths):
    """Edge Case: Smell persists but shifted line numbers in child commit."""
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "child", "parent_sha": "parent"}) + "\n")

    # Refactoring shifted from Parent (10-20) to Child (50-60)
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record("child", "src/A.java", "Move", 10, 20, 50, 60)) + "\n")

    with open(mock_paths["pmd"], "w") as f:
        # Smell is now at line 55 in child commit
        f.write(json.dumps(create_pmd_7_record("child", "src/A.java", "Complexity", 55, 55)) + "\n")

    df = ASTProximityStrategy().execute({
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }, None).collect()

    assert len(df) == 1
    assert df["score_AST_Proximity"][0] == 1.0
    assert df["causality_type"][0] == "Persistent"


# --- 3. Path Normalization Edge Case ---

def test_windows_absolute_path_normalization(mock_paths):
    """Edge Case: PMD uses Windows absolute paths, RefMiner uses relative."""
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record("c1", "src/org/App.java", "Rename", 1, 10, 1, 10)) + "\n")

    with open(mock_paths["pmd"], "w") as f:
        # Simulate messy Windows environment
        messy_path = r"C:\Jenkins\Workspace\src\org\App.java"
        f.write(json.dumps(create_pmd_7_record("c1", messy_path, "Complexity", 5, 5)) + "\n")

    df = ASTProximityStrategy().execute({
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }, None).collect()

    assert len(df) == 1
    assert df["file_path"][0] == "src/org/App.java"
    assert df["score_AST_Proximity"][0] == 1.0