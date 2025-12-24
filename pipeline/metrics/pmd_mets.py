import json
import statistics
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics


class PMDMetrics(BaseMetrics):

    def get_tool_name(self) -> str:
        return "PMD Metrics"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"pmd_metrics_{project_name}.json"

    def load_data(self):
        project_name = self.target_repo_path.name

        pmd_path = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"
        repo_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        # [ORGANIZATION] Search in the new raw subfolder first
        raw_batch_dir = config.OUTPUTS_PATH / "pmd_raw" / project_name

        aggregated_data = {"files": []}
        found_data = False

        # Strategy 1: Check for Batch Files in Subfolder
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
                    except Exception:
                        pass
                found_data = True

        # Strategy 2: Fallback to root (Legacy Support)
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
                    except Exception:
                        pass
                found_data = True

        # Strategy 3: Standard Snapshot File
        if not found_data and pmd_path.exists():
            try:
                with open(pmd_path, 'r') as f:
                    return (json.load(f), 1)  # Return immediately
            except json.JSONDecodeError:
                return None

        if not found_data:
            print(f"   ❌ No PMD data found.")
            return None

        file_count = 1
        if repo_path.exists():
            with open(repo_path, 'r') as f:
                repo_data = json.load(f)
                file_count = repo_data.get("content", {}).get("java_file_count", 1)

        return (aggregated_data, file_count)

    def calculate(self, data) -> dict:
        pmd_data, file_count = data
        files = pmd_data.get("files", [])

        pmd_conf = config.HEURISTICS.get("pmd", {})
        COMPLEXITY_RULE_NAME = pmd_conf.get("complexity_rule", "CyclomaticComplexity")
        HOTSPOT_LIMIT = pmd_conf.get("hotspot_limit", 5)

        total_smells = 0
        complexity_scores = []
        hotspots = {}

        for f in files:
            violations = f.get("violations", [])
            count = len(violations)
            total_smells += count

            fname = Path(f["filename"]).name
            hotspots[fname] = hotspots.get(fname, 0) + count

            for v in violations:
                if v.get("rule") == COMPLEXITY_RULE_NAME:
                    desc = v.get("description", "")
                    # [REFACTOR] Specific Exception Handling
                    # Catches parsing errors, but lets SystemExit/KeyboardInterrupt through
                    try:
                        score = int(desc.split("complexity of")[-1].strip(" ."))
                        complexity_scores.append(score)
                    except (ValueError, IndexError, AttributeError):
                        pass

        density = total_smells / file_count if file_count > 0 else 0
        avg_comp = statistics.mean(complexity_scores) if complexity_scores else 0

        top_hotspots = dict(sorted(hotspots.items(), key=lambda x: x[1], reverse=True)[:HOTSPOT_LIMIT])

        return {
            "density": {"total_smells": total_smells, "per_file": round(density, 2)},
            "complexity": {
                "metric_used": COMPLEXITY_RULE_NAME,
                "avg_score": round(avg_comp, 1)
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