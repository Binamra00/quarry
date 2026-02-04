import pytest
import json
from pipeline.heuristics.dto_loader import DTOLoader


@pytest.fixture
def mock_files(tmp_path):
    return {
        "ref": tmp_path / "refactorings.jsonl",
        "pmd": tmp_path / "pmd_history.jsonl",
        "lin": tmp_path / "lineage.jsonl"
    }


# --- 1. Regex Robustness Tests ---

def test_path_normalization_windows(mock_files):
    """Verify that absolute Windows paths are stripped to relative paths."""
    # Mock RefMiner output with Windows paths
    data = {
        "repository": "repo",
        "sha1": "abc",
        "refactorings": [{
            "type": "Extract",
            "description": "desc",
            "leftSideLocations": [{
                "filePath": r"E:\Jenkins\Build\src\org\App.java",
                "startLine": 10, "endLine": 20
            }],
            "rightSideLocations": []
        }]
    }
    with open(mock_files["ref"], "w") as f:
        f.write(json.dumps(data) + "\n")

    df = DTOLoader.load_refactorings(str(mock_files["ref"])).collect()

    assert len(df) == 1
    # Should be normalized to 'src/org/App.java'
    assert df["file_path"][0] == "src/org/App.java"


def test_path_normalization_multiple_src(mock_files):
    """Verify regex doesn't greedily eat too much if 'src' appears twice."""
    # e.g. E:\Project\src\main\src\org\App.java
    data = {
        "repository": "repo",
        "sha1": "abc",
        "refactorings": [{
            "type": "Extract",
            "description": "desc",
            "leftSideLocations": [{
                # Anchored regex should preserve the inner src structure
                "filePath": r"E:\Project\src\main\src\org\App.java",
                "startLine": 10, "endLine": 20
            }],
            "rightSideLocations": []
        }]
    }
    with open(mock_files["ref"], "w") as f:
        f.write(json.dumps(data) + "\n")

    df = DTOLoader.load_refactorings(str(mock_files["ref"])).collect()

    # Expected behavior depends on your regex anchor strategy.
    # Current regex: ^.*?(src|source|lib)/ -> Replaces prefix up to FIRST src
    # So E:\Project\src\main\src\org\App.java -> src\main\src\org\App.java
    assert df["file_path"][0] == "src/main/src/org/App.java"


# --- 2. PMD Double-Nesting Tests ---

def test_pmd_double_nesting(mock_files):
    """Verify loader correctly extracting nested violations and score."""
    data = {
        "sha": "abc",
        "status": "success",
        "violations": [{
            "filename": "src/App.java",
            "violations": [{  # Inner nesting
                "rule": "GodClass",
                "priority": 1,
                "beginline": 10, "endline": 100,
                "description": "Complex",
                "metric_value": 50  # <--- [NEW] Raw Score added here
            }]
        }]
    }
    with open(mock_files["pmd"], "w") as f:
        f.write(json.dumps(data) + "\n")

    df = DTOLoader.load_pmd(str(mock_files["pmd"])).collect()

    assert len(df) == 1
    assert df["file_path"][0] == "src/App.java"
    assert df["rule_name"][0] == "GodClass"
    assert df["start_line"][0] == 10

    # [NEW] Verify score extraction and renaming
    assert df["pmd_complexity_score"][0] == 50


# --- 3. Safety Tests (Empty Lists) ---

def test_refactoring_empty_right_side(mock_files):
    """Verify loader handles empty rightSideLocations without crashing."""
    data = {
        "repository": "repo",
        "sha1": "abc",
        "refactorings": [{
            "type": "Extract",
            "description": "desc",
            "leftSideLocations": [{"filePath": "src/A.java", "startLine": 1, "endLine": 2}],
            "rightSideLocations": []  # Empty!
        }]
    }
    with open(mock_files["ref"], "w") as f:
        f.write(json.dumps(data) + "\n")

    df = DTOLoader.load_refactorings(str(mock_files["ref"])).collect()

    assert len(df) == 1
    # Should result in nulls for right-side columns, not a crash
    assert df["start_line_ref_right"][0] is None


def test_refactoring_rename_columns(mock_files):
    """
    [NEW] Verify that 'left_side_path' and 'right_side_path' are correctly
    extracted for Move/Rename refactorings.
    """
    # 1. Mock Data: A "Move Class" refactoring (Old -> New)
    data = {
        "repository": "repo",
        "sha1": "commit_123",
        "refactorings": [{
            "type": "Move Class",
            "description": "Move Class src.Old moved to src.New",
            "leftSideLocations": [{
                "filePath": "src/Old.java",
                "startLine": 10, "endLine": 20
            }],
            "rightSideLocations": [{
                "filePath": "src/New.java",
                "startLine": 15, "endLine": 25
            }]
        }]
    }

    # 2. Write to mock file
    with open(mock_files["ref"], "w") as f:
        f.write(json.dumps(data) + "\n")

    # 3. Execute Loader
    df = DTOLoader.load_refactorings(str(mock_files["ref"])).collect()

    # 4. Assertions
    assert len(df) == 1
    # Verify the split paths exist and are correct
    assert df["left_side_path"][0] == "src/Old.java"
    assert df["right_side_path"][0] == "src/New.java"

    # [NEW] Verify that file_path defaults to the Right Side (New Location)
    assert df["file_path"][0] == "src/New.java"

    # Verify the line numbers map correctly
    assert df["start_line_ref_left"][0] == 10
    assert df["start_line_ref_right"][0] == 15
