import json
import sys
from pathlib import Path
from typing import Dict, Any

from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics
from pipeline.metrics.formulas import StandardStaticLogic, IStaticAnalysisLogic


class PMDMetrics(BaseMetrics):

    def __init__(self, target_repo_path: Path):
        super().__init__(target_repo_path)
        self.logic: IStaticAnalysisLogic = StandardStaticLogic()
        self.PULSE_SIZE_LINES = 5000

    def get_tool_name(self) -> str:
        return "PMD Metrics (Pulse Stream)"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"pmd_metrics_{project_name}.json"

    def load_data(self) -> Dict[str, Any]:
        """
        [Template Pattern Implementation]
        Instead of loading the massive file (which breaks memory), this prepares
        the 'Context' required for the calculation step.
        """
        project_name = self.target_repo_path.name

        # 1. Prepare Paths
        jsonl_path = config.OUTPUTS_PATH / f"pmd_history_{project_name}.jsonl"
        repo_metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        # 2. Check Existence (Fail fast if no data exists)
        if not jsonl_path.exists():
            print(f"   ❌ History Stream not found: {jsonl_path}")
            return None  # Template will abort cleanly

        # 3. Load Metadata (Lightweight)
        file_count = 1
        if repo_metrics_path.exists():
            try:
                with open(repo_metrics_path, 'r') as f:
                    repo_data = json.load(f)
                    file_count = repo_data.get("content", {}).get("java_file_count", 1)
            except json.JSONDecodeError:
                print(f"   ⚠️ Warning: repo_metrics.json corrupt. Defaulting to 1.", file=sys.stderr)

        # 4. Return Context Object (Always Truthy)
        return {
            "stream_path": jsonl_path,
            "file_count": file_count
        }

    def calculate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        [Template Pattern Implementation]
        Receives the context from load_data() and performs the O(1) Streaming Calculation.
        """
        jsonl_path = context["stream_path"]
        file_count = context["file_count"]

        print(f"   📊 Starting Pulse-Stream analysis of {jsonl_path.name}...")

        # --- Initialize Logic ---
        stats = {
            "total_smells": 0,
            "complexity_sum": 0,
            "complexity_count": 0,
            "hotspots_map": {},
            "commits_processed": 0
        }

        COMPLEXITY_RULE_NAME = "CyclomaticComplexity"
        HOTSPOT_LIMIT = 5

        # --- Pulse Loop (The I/O Engine) ---
        file_offset = 0
        has_more_data = True
        pulse_count = 0

        while has_more_data:
            lines_in_pulse = 0

            with open(jsonl_path, 'r', encoding='utf-8') as f:
                f.seek(file_offset)

                while lines_in_pulse < self.PULSE_SIZE_LINES:
                    line = f.readline()
                    if not line:
                        has_more_data = False
                        break

                    lines_in_pulse += 1
                    if not line.strip(): continue

                    try:
                        record = json.loads(line)
                        if record.get("status", "success") != "success":
                            continue

                        stats["commits_processed"] += 1
                        self._process_violations(record.get("violations", []), stats, COMPLEXITY_RULE_NAME)

                    except json.JSONDecodeError:
                        continue

                file_offset = f.tell()

            pulse_count += 1
            if pulse_count % 20 == 0:
                print(f"      ... Processed {stats['commits_processed']} commits ...")

        # --- Aggregation ---
        avg_comp = 0
        if stats["complexity_count"] > 0:
            avg_comp = stats["complexity_sum"] / stats["complexity_count"]

        # Hotspot identification
        sorted_hotspots = sorted(stats["hotspots_map"].items(), key=lambda x: x[1], reverse=True)[:HOTSPOT_LIMIT]
        top_hotspots = dict(sorted_hotspots)

        density = 0
        if file_count > 0:
            density = stats["total_smells"] / file_count

        return {
            "density": {
                "total_smells": stats["total_smells"],
                "per_file": round(density, 2),
                "strategy": "PulseStreaming"
            },
            "complexity": {
                "metric_used": COMPLEXITY_RULE_NAME,
                "avg_score": round(avg_comp, 1),
                "strategy": "PulseStreaming"
            },
            "hotspots": top_hotspots
        }

    def _process_violations(self, files_list, stats, comp_rule):
        """Helper to update running counters."""
        for f in files_list:
            violations = f.get("violations", [])
            count = len(violations)

            stats["total_smells"] += count

            fname = Path(f["filename"]).name
            stats["hotspots_map"][fname] = stats["hotspots_map"].get(fname, 0) + count

            for v in violations:
                if "metric_value" in v and v.get("rule") == comp_rule:
                    stats["complexity_sum"] += v["metric_value"]
                    stats["complexity_count"] += 1
                elif v.get("rule") == comp_rule:
                    desc = v.get("description", "")
                    try:
                        score = int(desc.split("complexity of")[-1].strip(" ."))
                        stats["complexity_sum"] += score
                        stats["complexity_count"] += 1
                    except (ValueError, IndexError, AttributeError):
                        pass

    def print_report(self, metrics: dict):
        d = metrics["density"]
        c = metrics["complexity"]
        print(f"├── [Density] (Cumulative History)")
        print(f"│   ├── Total Smells: {d['total_smells']}")
        print(f"│   └── Smells/File:  {d['per_file']}")
        print(f"├── [Complexity]")
        print(f"│   ├── Metric: {c['metric_used']}")
        print(f"│   └── Avg Score:  {c['avg_score']}")
        print(f"├── [Hotspots]")
        for f, count in metrics["hotspots"].items():
            print(f"│   ├── {f}: {count}")