import json
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics


class RefmMetrics(BaseMetrics):

    def get_tool_name(self) -> str:
        return "RefactoringMiner Metrics"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"refactoring_metrics_{project_name}.json"

    def load_data(self):
        # [DECOUPLING] Dynamic loading based on project name
        project_name = self.target_repo_path.name

        refm_json_path = config.OUTPUTS_PATH / f"refactorings_{project_name}.json"
        repo_metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        if not refm_json_path.exists():
            print(f"⚠️ Refactoring output not found: {refm_json_path.name}")
            return None

        # 1. Load RefactoringMiner Output
        try:
            with open(refm_json_path, 'r') as f:
                refm_data = json.load(f)
        except json.JSONDecodeError:
            print("❌ Error decoding RefactoringMiner JSON")
            return None

        # 2. Load Repo Metrics (Context & Churn Map)
        total_commits = 0
        churn_map = {}

        if repo_metrics_path.exists():
            try:
                with open(repo_metrics_path, 'r') as f:
                    repo_data = json.load(f)
                    total_commits = repo_data.get("history", {}).get("total_commits", 0)
                    churn_map = repo_data.get("churn_map", {})
            except json.JSONDecodeError:
                print("⚠️ Error decoding RepoMetrics JSON (Context missing)")
        else:
            print("⚠️ RepoMetrics file missing. Purity analysis may be inaccurate.")

        return (refm_data, total_commits, churn_map)

    def calculate(self, data) -> dict:
        refm_data, total_commits, churn_map = data
        refm_conf = config.HEURISTICS.get("refactoring", {})
        CHURN_SENSITIVITY = refm_conf.get("churn_sensitivity", 20)

        commits_list = refm_data.get("commits", [])
        commits_with_refs = len(commits_list)
        total_ops = 0
        high_churn_refs = 0
        ref_types = {}

        for commit in commits_list:
            refs = commit.get("refactorings", [])
            count = len(refs)
            total_ops += count
            sha1 = commit.get("sha1")
            churn = int(churn_map.get(sha1, 0))

            if churn > (count * CHURN_SENSITIVITY):
                high_churn_refs += 1

            for r in refs:
                t = r.get("type", "Unknown")
                ref_types[t] = ref_types.get(t, 0) + 1

        density = (commits_with_refs / total_commits * 100) if total_commits > 0 else 0
        purity = ((commits_with_refs - high_churn_refs) / commits_with_refs * 100) if commits_with_refs > 0 else 0

        sorted_types = dict(sorted(ref_types.items(), key=lambda x: x[1], reverse=True)[:10])

        return {
            "scope": {
                "total_commits": total_commits,
                "commits_with_refs": commits_with_refs,
                "density_percent": round(density, 2)
            },
            "purity": {
                "floss_commits": high_churn_refs,
                "purity_score": round(purity, 2)
            },
            "top_types": sorted_types
        }

    def print_report(self, metrics: dict):
        s = metrics["scope"]
        p = metrics["purity"]
        refm_conf = config.HEURISTICS.get("refactoring", {})
        TARGET_DENSITY = refm_conf.get("density_target_percent", 40.0)
        TARGET_PURITY = refm_conf.get("purity_target_percent", 80.0)

        print(f"├── [Dataset Scope]")
        print(f"│   ├── Total Commits: {s['total_commits']}")
        print(f"│   └── Refactoring Density: {s['density_percent']}% (Target: >{TARGET_DENSITY}%)")
        print(f"├── [Dataset Purity]")
        print(f"│   ├── Floss Commits: {p['floss_commits']}")
        print(f"│   └── Purity Score:  {p['purity_score']}% (Target: >{TARGET_PURITY}%)")
        print(f"├── [Top Types]")
        for t, c in metrics["top_types"].items():
            print(f"│   ├── {t}: {c}")