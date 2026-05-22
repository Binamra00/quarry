import json
import sys
from pathlib import Path
from typing import Dict, Any

from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics
from pipeline.metrics.formulas import StandardRefactoringLogic, IRefactoringAnalysisLogic


class RefmMetrics(BaseMetrics):
    """
    Refactoring Metrics Engine.
    Refactored to match PMD's 'Context-Based Streaming' architecture.
    """

    def __init__(self, target_repo_path: Path):
        super().__init__(target_repo_path)
        self.logic: IRefactoringAnalysisLogic = StandardRefactoringLogic()

    def get_tool_name(self) -> str:
        return "RefactoringMiner Metrics (Stream)"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"refm_metrics_{project_name}.json"

    def load_data(self) -> Dict[str, Any]:
        """
        [Template Pattern Implementation]
        Prepares the context (paths & churn map) for streaming.
        Does NOT load the refactoring JSONL into memory.
        """
        project_name = self.target_repo_path.name

        # 1. Paths
        jsonl_path = config.OUTPUTS_PATH / f"refactorings_{project_name}.jsonl"
        repo_metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        # 2. Load Churn Map (Metadata - Fits in Memory)
        # This is required for the "Purity Score" calculation in the streaming phase.
        churn_map = {}
        if repo_metrics_path.exists():
            try:
                with open(repo_metrics_path, 'r') as f:
                    data = json.load(f)
                    # Support legacy structure (root level vs 'content' key)
                    if "churn_map" in data:
                        churn_map = data["churn_map"]
                    elif "content" in data and "churn_map" in data["content"]:
                        churn_map = data["content"]["churn_map"]
            except json.JSONDecodeError:
                print(f"   ⚠️ Warning: Could not load Churn Map from {repo_metrics_path.name}", file=sys.stderr)

        # 3. Check Data Existence
        if not jsonl_path.exists():
            print(f"   ❌ Refactoring Stream not found: {jsonl_path}")
            return None

        # 4. Return Context
        return {
            "stream_path": jsonl_path,
            "churn_map": churn_map
        }

    def calculate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        [Template Pattern Implementation]
        Streams the JSONL file to calculate aggregates O(1) memory style.
        """
        jsonl_path = context["stream_path"]
        churn_map = context["churn_map"]

        print(f"   📊 Streaming analysis of {jsonl_path.name}...")

        # --- Initialize Aggregators ---
        stats = {
            "total_refactorings": 0,
            "commits_with_refactorings": 0,
            "type_counts": {},  # { "Extract Method": 120, ... }
            "purity_scores": [],  # List of floats (Memory efficient)
            "locations_map": {}  # For hotspots
        }

        HOTSPOT_LIMIT = 5  # Top N locations to track

        # --- Stream Processing ---
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue

                try:
                    record = json.loads(line)

                    # Extract Data Points
                    ref_list = record.get("refactorings", [])
                    sha = record.get("sha", "")

                    if not ref_list:
                        continue

                    stats["commits_with_refactorings"] += 1
                    commit_total_churn = churn_map.get(sha, 0)

                    # Purity Calculation (Delegate to Logic)
                    purity = self.logic.calculate_commit_purity(ref_list, commit_total_churn)
                    if purity is not None:
                        stats["purity_scores"].append(purity)

                    # Update Counts & Hotspots
                    for r in ref_list:
                        stats["total_refactorings"] += 1

                        # Type Counting
                        r_type = r.get("type", "Unknown")
                        stats["type_counts"][r_type] = stats["type_counts"].get(r_type, 0) + 1

                        # Hotspot Tracking
                        # Prioritize leftSide (Original Location) for causality
                        locs = r.get("leftSideLocations", [])
                        if not locs:
                            locs = r.get("rightSideLocations", [])

                        for loc in locs:
                            path = Path(loc.get("filePath", ""))
                            filename = path.name
                            stats["locations_map"][filename] = stats["locations_map"].get(filename, 0) + 1

                except json.JSONDecodeError:
                    continue

        # --- Final Aggregation ---
        # Delegate math to the 'Logic' component (Strategy Pattern)
        avg_purity = self.logic.calculate_purity_aggregation(stats["purity_scores"])
        top_hotspots = self.logic.identify_hotspots(stats["locations_map"], HOTSPOT_LIMIT)

        # Sort types by frequency
        sorted_types = dict(sorted(stats["type_counts"].items(), key=lambda item: item[1], reverse=True))

        return {
            "summary": {
                "total_refactorings": stats["total_refactorings"],
                "commits_analyzed": stats["commits_with_refactorings"],
                "avg_purity_score": round(avg_purity, 2)
            },
            "refactoring_types": sorted_types,
            "hotspots": top_hotspots
        }

    def print_report(self, metrics: dict):
        s = metrics["summary"]
        print(f"├── [Summary]")
        print(f"│   ├── Total Refs: {s['total_refactorings']}")
        print(f"│   ├── Avg Purity: {s['avg_purity_score']}%")
        print(f"├── [Top Refactoring Types]")
        for k, v in list(metrics["refactoring_types"].items())[:3]:
            print(f"│   ├── {k}: {v}")