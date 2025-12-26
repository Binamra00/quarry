import json
import statistics
import sys
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics
from pipeline.metrics.formulas import StandardStaticLogic, IStaticAnalysisLogic


class PMDMetrics(BaseMetrics):

    def __init__(self, target_repo_path: Path):
        super().__init__(target_repo_path)
        self.logic: IStaticAnalysisLogic = StandardStaticLogic()

    def get_tool_name(self) -> str:
        return "PMD Metrics"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"pmd_metrics_{project_name}.json"

    def load_data(self):
        """
        Loads PMD data from the new JSONL Stream (Phase 3.2)
        Falls back to legacy directory globbing if stream is missing.
        """
        project_name = self.target_repo_path.name

        # [NEW] Primary Source: The JSONL History Stream
        jsonl_path = config.OUTPUTS_PATH / f"pmd_history_{project_name}.jsonl"

        # Legacy/Auxiliary paths
        repo_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"
        raw_batch_dir = config.OUTPUTS_PATH / "pmd_raw" / project_name

        aggregated_data = {"files": []}
        found_data = False
        processed_commits = 0

        # ---------------------------------------------------------
        # STRATEGY 1: Stream Loading (New Architecture)
        # ---------------------------------------------------------
        if jsonl_path.exists():
            print(f"   📊 Found JSONL history stream: {jsonl_path.name}. Aggregating...")
            try:
                with open(jsonl_path, 'r') as f:
                    for line_num, line in enumerate(f):
                        line = line.strip()
                        # [FIX] PEP 8: Avoid compound statements
                        if not line:
                            continue

                        try:
                            record = json.loads(line)

                            # [LOGIC] Only aggregate successful runs
                            # If 'status' is missing (legacy data), assume success
                            status = record.get("status", "success")

                            if status == "success":
                                # Map the 'violations' field from JSONL to the 'files' list
                                # expected by the calculation logic.
                                file_violations = record.get("violations", [])
                                if file_violations:
                                    aggregated_data["files"].extend(file_violations)

                                # [FIX] Increment for ALL successful commits, even if 0 violations
                                processed_commits += 1

                        except json.JSONDecodeError:
                            print(f"   ⚠️ Skipping corrupt line {line_num + 1} in JSONL", file=sys.stderr)

                found_data = True
                print(f"   ✅ Aggregated valid data from {processed_commits} historical commits.")

            except Exception as e:
                print(f"   ❌ Error reading JSONL stream: {e}", file=sys.stderr)

        # ---------------------------------------------------------
        # STRATEGY 2: Legacy Batch Files (Fallback)
        # ---------------------------------------------------------
        if not found_data and raw_batch_dir.exists():
            batch_files = list(raw_batch_dir.glob("pmd_out_*.json"))
            if batch_files:
                print(f"   ⚠️ JSONL missing. Falling back to {len(batch_files)} legacy batch files...")
                for bf in batch_files:
                    try:
                        with open(bf, 'r') as f:
                            data = json.load(f)
                            if "files" in data:
                                aggregated_data["files"].extend(data["files"])
                    except (json.JSONDecodeError, OSError) as e:
                        print(f"   ⚠️ Data Loss: Skipping corrupt batch file {bf.name} -> {e}", file=sys.stderr)
                found_data = True

        if not found_data:
            print(f"   ❌ No PMD data found (Checked JSONL stream and Legacy directory).")
            return None

        # ---------------------------------------------------------
        # Metadata Loading
        # ---------------------------------------------------------
        file_count = 1
        if repo_path.exists():
            try:
                with open(repo_path, 'r') as f:
                    repo_data = json.load(f)
                    file_count = repo_data.get("content", {}).get("java_file_count", 1)
            except json.JSONDecodeError:
                print(f"   ⚠️ Warning: repo_metrics.json is corrupt. Defaulting file count to 1.", file=sys.stderr)

        return (aggregated_data, file_count)

    def calculate(self, data) -> dict:
        """Pure Business Logic."""
        pmd_data, file_count = data
        files = pmd_data.get("files", [])

        pmd_conf = config.HEURISTICS.get("pmd", {})
        COMPLEXITY_RULE_NAME = pmd_conf.get("complexity_rule", "CyclomaticComplexity")
        HOTSPOT_LIMIT = pmd_conf.get("hotspot_limit", 5)

        total_smells = 0
        complexity_scores = []
        hotspots_map = {}

        for f in files:
            violations = f.get("violations", [])
            count = len(violations)
            total_smells += count

            fname = Path(f["filename"]).name
            hotspots_map[fname] = hotspots_map.get(fname, 0) + count

            for v in violations:
                if v.get("rule") == COMPLEXITY_RULE_NAME:
                    desc = v.get("description", "")
                    try:
                        score = int(desc.split("complexity of")[-1].strip(" ."))
                        complexity_scores.append(score)
                    except (ValueError, IndexError, AttributeError):
                        pass

        density = self.logic.calculate_density(total_smells, file_count)
        avg_comp = self.logic.calculate_complexity_aggregation(complexity_scores)
        top_hotspots = self.logic.identify_hotspots(hotspots_map, HOTSPOT_LIMIT)

        return {
            "density": {
                "total_smells": total_smells,
                "per_file": round(density, 2),
                "strategy": self.logic.__class__.__name__
            },
            "complexity": {
                "metric_used": COMPLEXITY_RULE_NAME,
                "avg_score": round(avg_comp, 1),
                "strategy": self.logic.__class__.__name__
            },
            "hotspots": top_hotspots
        }

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