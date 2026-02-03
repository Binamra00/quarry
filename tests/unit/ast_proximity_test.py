import pytest
import json
import polars as pl
from pipeline.heuristics.strategies.ast_proximity import ASTProximityStrategy


@pytest.fixture
def mock_paths(tmp_path):
    """Fixture to provide temporary paths for mock data files."""
    return {
        "ref": tmp_path / "refactorings.jsonl",
        "pmd": tmp_path / "pmd_history.jsonl",
        "lin": tmp_path / "lineage.jsonl"
    }


def create_pmd_7_record(sha, filename, rule, start, end, score=10): # [CHANGED] Added score param with default
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
                "description": "Mock violation",
                "metric_value": score  # [NEW] Include the score in the mock data
            }]
        }]
    }


# tests/unit/ast_proximity_test.py

def create_ref_record(sha, filename, refactoring_type, l_start, l_end, r_start, r_end, right_filename=None):
    """
    Helper to create RefactoringMiner mock records.
    [UPDATED]: Allows specifying different filenames for left/right sides (Moves/Renames).
    """
    if right_filename is None:
        right_filename = filename

    return {
        "repository": "dummy_repo",
        "sha1": sha,
        "refactorings": [{
            "type": refactoring_type,
            "description": f"{refactoring_type} at {filename}",
            # [CRITICAL]: Structure matches new DTOLoader schema
            "leftSideLocations": [{"filePath": filename, "startLine": l_start, "endLine": l_end}],
            "rightSideLocations": [{"filePath": right_filename, "startLine": r_start, "endLine": r_end}]
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
    Test Case: Boundary Value Analysis - One Line Outside.
    Refactoring: 10-20. Smell: 21 (Start).
    Result should be NONE (Score 0.0), because it strictly falls outside.
    """
    # 1. Refactoring Data (Explicit - Bypassing DTO to test Logic)
    ref_df = pl.DataFrame({
        "repository": ["dummy_repo"],
        "commit_sha": ["c1"],
        "refactoring_type": ["Extract Method"],
        "description": ["Extract Method public foo..."],
        "left_side_path": ["src/A.java"],
        "right_side_path": ["src/A.java"],
        "file_path": ["src/A.java"],  # Primary path
        # Refactoring Range: 10-20
        "start_line_ref_left": [10], "end_line_ref_left": [20],
        "start_line_ref_right": [10], "end_line_ref_right": [20]
    }).lazy()

    # 2. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 3. PMD History
    with open(mock_paths["pmd"], "w") as f:
        # Parent: Smell at 21 (Just outside 10-20) -> Should NOT match
        f.write(json.dumps(create_pmd_7_record("p1", "src/A.java", "Rule1", 21, 25)) + "\n")
        # Current: Smell at 21 -> Should NOT match
        f.write(json.dumps(create_pmd_7_record("c1", "src/A.java", "Rule1", 21, 25)) + "\n")

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),  # Unused by logic but required by check
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    # We pass the dataframe directly
    result = strategy.execute(context, ref_df).collect()

    # 5. Assertions
    # Should be 0.0 because it is outside the range
    assert result["score_AST_Proximity"][0] == 0.0

    # Explicit assertion to verify causality classification for out-of-range smells
    assert result["causality_type"][0] == "None"

    assert result["left_smell"][0] is False
    assert result["right_smell"][0] is False


# --- 2. Edge Case: Coordinate Shift ---

def test_persistent_with_coordinate_shift(mock_paths):
    """
    Test Case: Persistent Smell with Coordinate Shift.
    Parent: Ref(10-20), Smell(10-20) -> Match
    Current: Ref(30-40), Smell(30-40) -> Match
    Result: Persistent
    """
    # 1. Refactoring Data (Explicit)
    ref_df = pl.DataFrame({
        "repository": ["dummy_repo"],
        "commit_sha": ["c1"],
        "refactoring_type": ["Extract Method"],
        "description": ["Extract Method..."],
        "left_side_path": ["src/A.java"],
        "right_side_path": ["src/A.java"],
        "file_path": ["src/A.java"],
        # Parent Range: 10-20
        "start_line_ref_left": [10], "end_line_ref_left": [20],
        # Current Range: 30-40 (Shifted)
        "start_line_ref_right": [30], "end_line_ref_right": [40]
    }).lazy()

    # 2. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 3. PMD History
    with open(mock_paths["pmd"], "w") as f:
        # Parent: Smell at 10-20 (Matches Left)
        f.write(json.dumps(create_pmd_7_record("p1", "src/A.java", "Rule1", 10, 20)) + "\n")
        # Current: Smell at 30-40 (Matches Right)
        f.write(json.dumps(create_pmd_7_record("c1", "src/A.java", "Rule1", 30, 40)) + "\n")

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }
    result = strategy.execute(context, ref_df).collect()

    # 5. Assertions
    assert result["score_AST_Proximity"][0] == 1.0
    assert result["causality_type"][0] == "Persistent"
    assert result["left_smell"][0] is True
    assert result["right_smell"][0] is True


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

    # 1. Normalization verification:
    # If the Windows backslashes weren't normalized to Unix slashes,
    # this join would return 0 rows. The fact that it is 1 proves normalization worked.
    assert len(df) == 1

    # Note: Previously asserted df["file_path"][0] == "src/org/App.java" but this
    # column was dropped for ML hygiene.

    assert df["score_AST_Proximity"][0] == 1.0


def test_chaining_preserves_columns(mock_paths):
    """
    Integration Test: Verifies that AST Proximity acts as a 'Good Pipe'.
    It should accept an incoming DataFrame (from Heuristic A) and preserve
    its columns (e.g., complexity_score) instead of dropping them.
    """
    # 1. Simulate Incoming Data from Heuristic A (Complexity)
    incoming_df = pl.DataFrame({
        "repository": ["dummy_path"],
        "commit_sha": ["c1"],
        # [NEW] Explicit Left/Right paths required by the updated Strategy
        "left_side_path": ["src/A.java"],
        "right_side_path": ["src/A.java"],
        "file_path": ["src/A.java"],
        "refactoring_type": ["Extract Method"],
        "start_line_ref_left": [10],
        "end_line_ref_left": [20],
        "start_line_ref_right": [10],
        "end_line_ref_right": [20],
        # [CRITICAL] Columns from Heuristic A
        "complexity_score": [1.0],
        "impact_category": ["High_Arch"]
    }).lazy()

    # 2. Setup Dependencies (Lineage & PMD)
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    with open(mock_paths["pmd"], "w") as f:
        f.write(json.dumps(create_pmd_7_record("c1", "src/A.java", "Rule", 10, 20)) + "\n")

    # 3. Execute with 'incoming_df' passed as 'data'
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),  # Ignored but required by checks
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }

    result = strategy.execute(context, incoming_df).collect()

    # 4. Verify columns survived
    assert "complexity_score" in result.columns
    assert "impact_category" in result.columns
    assert result["complexity_score"][0] == 1.0
    # 5. Verify AST work was added
    assert "score_AST_Proximity" in result.columns
    assert result["score_AST_Proximity"][0] == 1.0


def test_true_fix_detection(mock_paths):
    """
    Test Case: Strong Causality (True Fix).
    Smell exists in Parent, but NOT in Current.
    """
    # 1. Setup Data
    # Refactoring: 10-20 (Parent) -> 10-20 (Current)
    ref_df = pl.DataFrame({
        "repository": ["dummy_repo"],
        "commit_sha": ["c1"],
        "refactoring_type": ["Extract Method"],
        "description": ["Extract Method..."],
        "left_side_path": ["src/A.java"],
        "right_side_path": ["src/A.java"],
        "file_path": ["src/A.java"],
        "start_line_ref_left": [10], "end_line_ref_left": [20],
        "start_line_ref_right": [10], "end_line_ref_right": [20]
    }).lazy()

    # 2. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 3. PMD: Smell ONLY in Parent (p1)
    with open(mock_paths["pmd"], "w") as f:
        f.write(json.dumps(create_pmd_7_record("p1", "src/A.java", "Rule1", 12, 15)) + "\n")
        # Current commit (c1) has NO smells

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }
    result = strategy.execute(context, ref_df).collect()

    # 5. Assert
    assert result["score_AST_Proximity"][0] == 1.0
    assert result["causality_type"][0] == "Fixed"

    # [NEW] Verify Explainability Booleans
    assert result["left_smell"][0] is True
    assert result["right_smell"][0] is False


def test_rename_file_persistence(mock_paths):
    """
    [NEW] Test Case: File Rename Support (Scenario B).
    The file is renamed from 'src/Old.java' to 'src/New.java'.
    The smell persists across the rename.
    """
    # 1. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 2. Refactoring (Rename Class)
    # Uses the updated helper to create split paths
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record(
            "c1", "src/Old.java", "Rename Class",
            10, 20, 10, 20,
            right_filename="src/New.java"  # <--- Key Change
        )) + "\n")

    # 3. PMD History
    with open(mock_paths["pmd"], "w") as f:
        # Parent Commit: Smell is in 'Old.java'
        f.write(json.dumps(create_pmd_7_record("p1", "src/Old.java", "Complex", 12, 15)) + "\n")
        # Current Commit: Smell is in 'New.java'
        f.write(json.dumps(create_pmd_7_record("c1", "src/New.java", "Complex", 12, 15)) + "\n")

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }
    result = strategy.execute(context, None).collect()

    # 5. Assert
    assert result["score_AST_Proximity"][0] == 1.0
    assert result["causality_type"][0] == "Persistent"
    # Verify we tracked it to the new file
    assert result["right_side_path"][0] == "src/New.java"
    # [NEW] Verify Explainability Booleans
    assert result["left_smell"][0] is True
    assert result["right_smell"][0] is True


def test_introduction_detection(mock_paths):
    """
    [NEW] Test Case: Introduction (Regression).
    Smell did NOT exist in Parent, but DOES exist in Current.
    """
    # 1. Refactoring Data
    ref_df = pl.DataFrame({
        "repository": ["dummy_repo"],
        "commit_sha": ["c1"],
        "refactoring_type": ["Extract Method"],
        "description": ["Extract Method..."],
        "left_side_path": ["src/A.java"],
        "right_side_path": ["src/A.java"],
        "file_path": ["src/A.java"],
        "start_line_ref_left": [10], "end_line_ref_left": [20],
        "start_line_ref_right": [10], "end_line_ref_right": [20],
    }).lazy()

    # 2. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 3. PMD History (Smell ONLY in Current)
    with open(mock_paths["pmd"], "w") as f:
        # Parent: Clean
        # Current: Has Smell
        f.write(json.dumps(create_pmd_7_record("c1", "src/A.java", "Complex", 12, 15)) + "\n")

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }
    result = strategy.execute(context, ref_df).collect()

    # 5. Assertions
    assert result["score_AST_Proximity"][0] == 1.0
    assert result["causality_type"][0] == "Introduction"
    assert result["left_smell"][0] is False
    assert result["right_smell"][0] is True

def test_amelioration_detection(mock_paths):
    """
    [NEW] Test Case: Amelioration (Revealed Preference).
    Smell persists, but score drops (20 -> 10).
    """
    # 1. Lineage
    with open(mock_paths["lin"], "w") as f:
        f.write(json.dumps({"commit_sha": "c1", "parent_sha": "p1"}) + "\n")

    # 2. Refactoring
    with open(mock_paths["ref"], "w") as f:
        f.write(json.dumps(create_ref_record("c1", "src/A.java", "Refactoring", 10, 20, 10, 20)) + "\n")

    # 3. PMD History
    with open(mock_paths["pmd"], "w") as f:
        # Parent: Score 20
        f.write(json.dumps(create_pmd_7_record("p1", "src/A.java", "Complex", 10, 20, score=20)) + "\n")
        # Current: Score 10 (Improved!)
        f.write(json.dumps(create_pmd_7_record("c1", "src/A.java", "Complex", 10, 20, score=10)) + "\n")

    # 4. Execute
    strategy = ASTProximityStrategy()
    context = {
        "refactorings_path": str(mock_paths["ref"]),
        "pmd_path": str(mock_paths["pmd"]),
        "lineage_path": str(mock_paths["lin"])
    }
    result = strategy.execute(context, None).collect()

    # 5. Assertions
    assert len(result) == 1
    assert result["causality_type"][0] == "Ameliorated"
    assert result["previous_pmd_score"][0] == 20
    assert result["current_pmd_score"][0] == 10