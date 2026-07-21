import json
from pathlib import Path
from typing import Dict, Any

from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics
from pipeline.metrics.formulas import StandardRefactoringLogic, IRefactoringAnalysisLogic
# NOTE: purity scoring removed -- it depended on a churn_map produced by the old repo_mets
# mining pass, which no longer exists. Type counts and hotspots need no churn.


class RefmMetrics(BaseMetrics):
    """
    Refactoring Metrics Engine.
    Uses a context-based streaming architecture (constant memory over the JSONL).
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
        Prepares the context (stream path) for streaming.
        Does NOT load the refactoring JSONL into memory.
        """
        project_name = self.target_repo_path.name

        # 1. Path to the RefactoringMiner stream
        jsonl_path = config.OUTPUTS_PATH / f"refactorings_{project_name}.jsonl"

        # 2. Check Data Existence
        if not jsonl_path.exists():
            print(f"   ❌ Refactoring Stream not found: {jsonl_path}")
            return None

        # 3. Return Context (no churn_map: purity scoring was removed)
        return {
            "stream_path": jsonl_path
        }

    def calculate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        [Template Pattern Implementation]
        Streams the JSONL file to calculate aggregates O(1) memory style.
        """
        jsonl_path = context["stream_path"]

        print(f"   📊 Streaming analysis of {jsonl_path.name}...")

        # --- Initialize Aggregators ---
        stats = {
            "total_refactorings": 0,
            "commits_with_refactorings": 0,
            "type_counts": {},   # { "Extract Method": 120, ... }
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

                    if not ref_list:
                        continue

                    stats["commits_with_refactorings"] += 1

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
        top_hotspots = self.logic.identify_hotspots(stats["locations_map"], HOTSPOT_LIMIT)

        # Sort types by frequency
        sorted_types = dict(sorted(stats["type_counts"].items(), key=lambda item: item[1], reverse=True))

        return {
            "summary": {
                "total_refactorings": stats["total_refactorings"],
                "commits_analyzed": stats["commits_with_refactorings"]
            },
            "refactoring_types": sorted_types,
            "hotspots": top_hotspots
        }

    def print_report(self, metrics: dict):
        s = metrics["summary"]
        print(f"├── [Summary]")
        print(f"│   ├── Total Refs: {s['total_refactorings']}")
        print(f"│   ├── Commits Analyzed: {s['commits_analyzed']}")
        print(f"├── [Top Refactoring Types]")
        for k, v in list(metrics["refactoring_types"].items())[:3]:
            print(f"│   ├── {k}: {v}")