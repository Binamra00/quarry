import json
import statistics
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics


class PMDMetrics(BaseMetrics):

    def get_tool_name(self) -> str:
        return "PMD Metrics"

    def get_output_path(self) -> Path:
        project_name = config.TOY_PROJECT_PATH.name
        return config.OUTPUTS_PATH / f"pmd_metrics_{project_name}.json"

    def load_data(self):
        project_name = config.TOY_PROJECT_PATH.name
        pmd_path = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"
        repo_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        if not pmd_path.exists():
            print(f"⚠️ PMD file missing: {pmd_path.name}")
            return None

        try:
            with open(pmd_path, 'r') as f:
                pmd_data = json.load(f)

            file_count = 1
            if repo_path.exists():
                with open(repo_path, 'r') as f:
                    repo_data = json.load(f)
                    file_count = repo_data.get("content", {}).get("java_file_count", 1)

            return (pmd_data, file_count)
        except json.JSONDecodeError:
            return None

    def calculate(self, data) -> dict:
        pmd_data, file_count = data
        files = pmd_data.get("files", [])

        total_smells = 0
        complexity_scores = []
        hotspots = {}

        for f in files:
            violations = f.get("violations", [])
            count = len(violations)
            total_smells += count
            hotspots[Path(f["filename"]).name] = count

            for v in violations:
                if v.get("rule") == "CyclomaticComplexity":
                    # Simple extraction logic
                    desc = v.get("description", "")
                    try:
                        score = int(desc.split("complexity of")[-1].strip(" ."))
                        complexity_scores.append(score)
                    except:
                        pass

        density = total_smells / file_count if file_count > 0 else 0
        avg_comp = statistics.mean(complexity_scores) if complexity_scores else 0

        top_hotspots = dict(sorted(hotspots.items(), key=lambda x: x[1], reverse=True)[:5])

        return {
            "density": {"total_smells": total_smells, "per_file": round(density, 2)},
            "complexity": {"avg_cyclomatic": round(avg_comp, 1)},
            "hotspots": top_hotspots
        }

    def print_report(self, metrics: dict):
        d = metrics["density"]
        c = metrics["complexity"]
        print(f"├── [Density]")
        print(f"│   ├── Total Smells: {d['total_smells']}")
        print(f"│   └── Smells/File:  {d['per_file']}")
        print(f"├── [Complexity]")
        print(f"│   └── Avg Cyclomatic: {c['avg_cyclomatic']}")
        print(f"├── [Hotspots]")
        for f, count in metrics["hotspots"].items():
            print(f"│   ├── {f}: {count}")


def calculate_pmd_metrics():
    PMDMetrics().run_report()