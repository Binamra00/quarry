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
        project_name = self.target_repo_path.name
        pmd_path = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"
        repo_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"
        raw_batch_dir = config.OUTPUTS_PATH / "pmd_raw" / project_name

        aggregated_data = {"files": []}
        found_data = False

        if raw_batch_dir.exists():
            batch_files = list(raw_batch_dir.glob("pmd_out_*.json"))
            if batch_files:
                print(f"   📊 Found {len(batch_files)} batch files in {raw_batch_dir.name}. Aggregating...")
                for bf in batch_files:
                    try:
                        with open(bf, 'r') as f:
                            data = json.load(f)
                            if "files" in data:
                                aggregated_data["files"].extend(data["files"])
                    except (json.JSONDecodeError, OSError) as e:
                        # [FIX] Standardized Log Format (Removed brackets)
                        print(f"   ⚠️ Data Loss: Skipping corrupt batch file {bf.name} -> {e}", file=sys.stderr)
                found_data = True

        if not found_data:
            batch_files_legacy = list(config.OUTPUTS_PATH.glob("pmd_out_*.json"))
            if batch_files_legacy:
                print(f"   ⚠️ Found legacy batch files in root. Aggregating...")
                for bf in batch_files_legacy:
                    try:
                        with open(bf, 'r') as f:
                            data = json.load(f)
                            if "files" in data:
                                aggregated_data["files"].extend(data["files"])
                    except (json.JSONDecodeError, OSError) as e:
                        # [FIX] Standardized Log Format
                        print(f"   ⚠️ Data Loss: Skipping corrupt legacy file {bf.name} -> {e}", file=sys.stderr)
                found_data = True

        if not found_data and pmd_path.exists():
            try:
                with open(pmd_path, 'r') as f:
                    return (json.load(f), 1)
            except json.JSONDecodeError:
                print(f"   ❌ Error: Snapshot file {pmd_path.name} is corrupt.", file=sys.stderr)
                return None

        if not found_data:
            print(f"   ❌ No PMD data found.")
            return None

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