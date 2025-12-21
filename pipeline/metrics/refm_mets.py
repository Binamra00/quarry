import json
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics

try:
    from pydriller import Repository
except ImportError:
    Repository = None


class RefmMetrics(BaseMetrics):

    def get_tool_name(self) -> str:
        return "RefactoringMiner Metrics"

    def get_output_path(self) -> Path:
        project_name = config.TOY_PROJECT_PATH.name
        return config.OUTPUTS_PATH / f"refactoring_metrics_{project_name}.json"

    def _get_churn_map(self):
        """Helper to mine churn for purity analysis."""
        churn_map = {}
        if Repository:
            print(f"   ... ⏳ Mining churn data for purity analysis ...")
            try:
                for commit in Repository(str(config.TOY_PROJECT_PATH)).traverse_commits():
                    total_churn = sum(f.added_lines + f.deleted_lines for f in commit.modified_files)
                    churn_map[commit.hash] = total_churn
            except Exception:
                pass
        return churn_map

    def load_data(self):
        """
        Impl: Loads Refactoring JSON AND Repo Metrics JSON (for total commits).
        """
        project_name = config.TOY_PROJECT_PATH.name
        refm_json_path = config.OUTPUTS_PATH / f"refactorings_{project_name}.json"
        repo_metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

        if not refm_json_path.exists():
            print(f"⚠️ Refactoring output not found: {refm_json_path.name}")
            return None

        # Load main data
        try:
            with open(refm_json_path, 'r') as f:
                refm_data = json.load(f)
        except json.JSONDecodeError:
            return None

        # Load context (Total Commits)
        total_commits = 0
        if repo_metrics_path.exists():
            try:
                with open(repo_metrics_path, 'r') as f:
                    repo_data = json.load(f)
                    total_commits = repo_data.get("history", {}).get("total_commits", 0)
            except:
                pass

        churn_map = self._get_churn_map()

        return (refm_data, total_commits, churn_map)

    def calculate(self, data) -> dict:
        refm_data, total_commits, churn_map = data

        commits_list = refm_data.get("commits", [])
        commits_with_refs = len(commits_list)
        total_ops = 0
        high_churn_refs = 0
        ref_types = {}

        for commit in commits_list:
            refs = commit.get("refactorings", [])
            count = len(refs)
            total_ops += count

            # Purity Check
            sha1 = commit.get("sha1")
            churn = churn_map.get(sha1, 0)
            if churn > (count * 20):  # Hardcoded heuristic (will fix in Task 4)
                high_churn_refs += 1

            for r in refs:
                t = r.get("type", "Unknown")
                ref_types[t] = ref_types.get(t, 0) + 1

        # Ratios
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

        print(f"├── [Dataset Scope]")
        print(f"│   ├── Total Commits: {s['total_commits']}")
        print(f"│   └── Refactoring Density: {s['density_percent']}%")
        print(f"├── [Dataset Purity]")
        print(f"│   ├── Floss Commits: {p['floss_commits']}")
        print(f"│   └── Purity Score:  {p['purity_score']}%")
        print(f"├── [Top Types]")
        for t, c in metrics["top_types"].items():
            print(f"│   ├── {t}: {c}")


def calculate_refm_metrics(ignored_arg=None):
    RefmMetrics().run_report()