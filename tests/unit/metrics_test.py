import json
from unittest.mock import patch, mock_open
from pathlib import Path
from pipeline.metrics.formulas import StandardRefactoringLogic, StandardStaticLogic
from pipeline.metrics.pmd_mets import PMDMetrics
from pipeline.metrics.refm_mets import RefmMetrics


# ==========================================
# CATEGORY A: PURE LOGIC (THE FORMULAS)
# ==========================================

class TestRefactoringFormulas:
    """Validates the mathematical laws in formulas.py"""

    def setup_method(self):
        self.logic = StandardRefactoringLogic(churn_sensitivity=20)

    def test_density_zero_division(self):
        """Test 1: Should return 0.0 if total history is 0 (Brand new repo)."""
        # Input: 0 total commits
        result = self.logic.calculate_density(ref_commits=5, total_commits=0)
        assert result == 0.0

    def test_purity_boundary_condition(self):
        """Test 2: BVA - Verify the exact churn threshold."""
        # Sensitivity is 20.
        # Case A: Ops=1, Churn=20 -> Pure (Borderline)
        assert self.logic.is_impure(churn=20, operation_count=1) is False

        # Case B: Ops=1, Churn=21 -> Impure (Crossed Line)
        assert self.logic.is_impure(churn=21, operation_count=1) is True

    def test_purity_score_zero_division(self):
        """Test 3: Should return 0.0 if no refactorings exist."""
        result = self.logic.calculate_purity_score(pure_commits=0, total_ref_commits=0)
        assert result == 0.0


class TestStaticAnalysisFormulas:
    """Validates the stats logic in formulas.py"""

    def setup_method(self):
        self.logic = StandardStaticLogic()

    def test_complexity_aggregation_empty(self):
        """Test 4: Should return 0.0 if input list is empty."""
        result = self.logic.calculate_complexity_aggregation([])
        assert result == 0.0

    def test_hotspot_sorting_logic(self):
        """Test 5: Should correctly sort and limit hotspots."""
        # Input: Unsorted map
        file_map = {"FileA": 10, "FileB": 50, "FileC": 5}
        limit = 2

        # Action
        result = self.logic.identify_hotspots(file_map, limit)

        # Assert: Order matters (Descending)
        keys = list(result.keys())
        assert keys[0] == "FileB"  # 50
        assert keys[1] == "FileA"  # 10
        assert len(result) == 2  # Limit respected


# ==========================================
# CATEGORY B: DATA SYNTHESIS (THE PARSERS)
# ==========================================

class TestPMDMetricsParser:
    """Validates robustness against bad data in pmd_mets.py"""

    def test_complexity_parsing_resilience(self):
        """Test 6: Should skip malformed complexity strings without crashing."""
        # Setup: Mock data with one GOOD and one BAD description
        metrics_engine = PMDMetrics(Path("dummy_repo"))

        mock_data = {
            "files": [
                {
                    "filename": "Good.java",
                    "violations": [
                        # Good Format
                        {"rule": "CyclomaticComplexity",
                         "description": "The class has a total cyclomatic complexity of 10 ."},
                        # Bad Format (Should be skipped)
                        {"rule": "CyclomaticComplexity", "description": "Complexity is unknown"}
                    ]
                }
            ]
        }

        # Action
        # Note: file_count=1 passed as second tuple element
        result = metrics_engine.calculate((mock_data, 1))

        # Assert
        # Average should be 10.0 (The bad value is ignored, not counted as 0)
        assert result["complexity"]["avg_score"] == 10.0


class TestRefmMetricsParser:
    """Validates robustness of refm_mets.py"""

    def test_missing_repo_context(self):
        """Test 7: Should handle missing repo_metrics.json (unknown churn)."""
        # Setup
        metrics_engine = RefmMetrics(Path("dummy_repo"))

        # Mock Input: Refactoring Data exists, but Churn Map (from Phase 0) is missing
        refm_data = {
            "commits": [
                {"sha1": "abc", "refactorings": [{"type": "Rename"}]}
            ]
        }
        total_commits = 100
        churn_map = {}  # EMPTY (Simulating missing file)

        # Action
        # We pass empty churn_map. The logic tries `churn_map.get(sha, 0)`
        result = metrics_engine.calculate((refm_data, total_commits, churn_map))

        # Assert
        # Should calculate using default churn=0 -> Pure
        assert result["purity"]["floss_commits"] == 0
        assert result["purity"]["purity_score"] == 100.0


class TestRefmMetricsLoading:
    """
    Validates data loading strategies in refm_mets.py.
    Covers JSONL streaming priority and Legacy JSON fallback.
    """

    def test_load_jsonl_priority(self):
        """Test 8: Should prioritize .jsonl if it exists."""
        metrics = RefmMetrics(Path("dummy_repo"))

        # Mock .jsonl content (Line-delimited JSON)
        jsonl_content = '{"sha1": "abc", "refactorings": []}\n{"sha1": "def", "refactorings": []}'

        # Mock existence: .jsonl exists
        def exists_side_effect(self):
            return str(self).endswith(".jsonl")

        with patch("pathlib.Path.exists", autospec=True, side_effect=exists_side_effect), \
                patch("builtins.open", mock_open(read_data=jsonl_content)) as mock_file:
            result = metrics.load_data()

            assert result is not None
            refm_data, _, _ = result
            assert len(refm_data["commits"]) == 2
            assert refm_data["commits"][0]["sha1"] == "abc"
            # Verify we opened the .jsonl file
            args, _ = mock_file.call_args
            assert ".jsonl" in str(args[0])

    def test_load_legacy_fallback(self):
        """Test 9: Should fallback to .json if .jsonl is missing."""
        metrics = RefmMetrics(Path("dummy_repo"))

        # Mock .json content (Monolithic)
        json_content = json.dumps({"commits": [{"sha1": "legacy", "refactorings": []}]})

        # Mock existence: .jsonl MISSING, .json EXISTS
        # Ensure repo_metrics returns False to avoid parsing collision in this unit test
        def exists_side_effect(self):
            path_str = str(self)
            if "repo_metrics" in path_str: return False
            return path_str.endswith(".json")

        with patch("pathlib.Path.exists", autospec=True, side_effect=exists_side_effect), \
                patch("builtins.open", mock_open(read_data=json_content)) as mock_file:
            result = metrics.load_data()

            assert result is not None
            refm_data, _, _ = result
            assert len(refm_data["commits"]) == 1
            assert refm_data["commits"][0]["sha1"] == "legacy"
            # Verify we opened the .json file
            args, _ = mock_file.call_args
            assert ".json" in str(args[0]) and ".jsonl" not in str(args[0])

    def test_load_missing_files(self):
        """Test 10: Should return None if neither file exists."""
        metrics = RefmMetrics(Path("dummy_repo"))

        with patch("pathlib.Path.exists", autospec=True, return_value=False):
            result = metrics.load_data()
            assert result is None