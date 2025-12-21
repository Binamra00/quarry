import os
import json
from collections import defaultdict, Counter
from pathlib import Path
from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics

try:
    from pydriller import Repository
except ImportError:
    Repository = None


class RepoMetrics(BaseMetrics):

    def get_tool_name(self) -> str:
        return "Repository Mining (Phase 0)"

    def get_output_path(self) -> Path:
        project_name = config.TOY_PROJECT_PATH.name
        return config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"

    def load_data(self):
        if not Repository:
            print("CRITICAL ERROR: PyDriller not installed.")
            return None

        repo_path = config.TOY_PROJECT_PATH
        print(f"   ... ⛏️ Mining raw history from: {repo_path.name}")

        stats = {
            "total_commits": 0,
            "fix_commits": 0,
            "refactor_commits": 0,
            "file_types": Counter(),
            "start_date": None,
            "end_date": None,
            "total_churn": 0
        }
        file_authors = defaultdict(set)
        pair_coupling = Counter()

        # [NEW] Load Keywords from Heuristics Configuration
        repo_conf = config.HEURISTICS.get("repo_mining", {})
        FIX_KEYWORDS = repo_conf.get("fix_keywords", ['fix', 'bug', 'issue'])
        REFACTOR_KEYWORDS = repo_conf.get("refactor_keywords", ['refactor', 'cleanup'])

        for commit in Repository(str(repo_path)).traverse_commits():
            stats["total_commits"] += 1
            if stats["start_date"] is None:
                stats["start_date"] = commit.committer_date
            stats["end_date"] = commit.committer_date

            msg_lower = commit.msg.lower()
            if any(kw in msg_lower for kw in FIX_KEYWORDS):
                stats["fix_commits"] += 1
            if any(kw in msg_lower for kw in REFACTOR_KEYWORDS):
                stats["refactor_commits"] += 1

            modified_java_files = []
            for file in commit.modified_files:
                ext = os.path.splitext(file.filename)[1] if file.filename else ".no_ext"
                stats["file_types"][ext] += 1

                if file.filename.endswith('.java'):
                    modified_java_files.append(file.filename)
                    churn = file.added_lines + file.deleted_lines
                    stats["total_churn"] += churn
                    file_authors[file.filename].add(commit.author.name)

            if len(modified_java_files) > 1:
                modified_java_files.sort()
                for i in range(len(modified_java_files)):
                    for j in range(i + 1, len(modified_java_files)):
                        pair = (modified_java_files[i], modified_java_files[j])
                        pair_coupling[pair] += 1

        return (stats, file_authors, pair_coupling)

    def calculate(self, data) -> dict:
        stats, file_authors, pair_coupling = data

        total = stats["total_commits"]
        fix_ratio = (stats["fix_commits"] / total * 100) if total > 0 else 0
        refactor_ratio = (stats["refactor_commits"] / total * 100) if total > 0 else 0
        avg_churn = (stats["total_churn"] / total) if total > 0 else 0

        age_days = 0
        if stats["start_date"] and stats["end_date"]:
            age_days = (stats["end_date"] - stats["start_date"]).days

        avg_bus_factor = 0
        if file_authors:
            avg_bus_factor = sum(len(a) for a in file_authors.values()) / len(file_authors)

        top_pair_name = "None"
        if pair_coupling:
            top = pair_coupling.most_common(1)[0]
            top_pair_name = f"{Path(top[0][0]).name} + {Path(top[0][1]).name} ({top[1]})"

        top_file_type = stats["file_types"].most_common(1)
        main_lang = top_file_type[0][0] if top_file_type else "Unknown"

        return {
            "project_name": config.TOY_PROJECT_PATH.name,
            "history": {
                "total_commits": total,
                "age_days": age_days,
                "start_date": str(stats["start_date"]),
                "end_date": str(stats["end_date"])
            },
            "content": {
                "main_language": main_lang,
                "java_file_count": len(file_authors),
                "total_churn": stats["total_churn"],
                "avg_churn_per_commit": round(avg_churn, 2)
            },
            "heuristics": {
                "bug_fix_ratio": round(fix_ratio, 2),
                "refactor_ratio": round(refactor_ratio, 2),
                "bus_factor": round(avg_bus_factor, 2),
                "top_coupling": top_pair_name
            }
        }

    def print_report(self, metrics: dict):
        h = metrics["history"]
        c = metrics["content"]
        heu = metrics["heuristics"]

        print(f"Project: {metrics['project_name']}")
        print(f"├── [History] Total Commits:    {h['total_commits']}")
        print(f"├── [History] Age (Days):       {h['age_days']} days")
        print(f"│")
        print(f"├── [Content] Main Language:    {c['main_language']}")
        print(f"├── [Content] Java Files:       {c['java_file_count']}")
        print(f"├── [Content] Total Churn:      {c['total_churn']} lines")
        print(f"│")
        print(f"├── [Heuristic] Bug-Fixes:      {heu['bug_fix_ratio']}%")
        print(f"├── [Heuristic] Refactorings:   {heu['refactor_ratio']}%")
        print(f"├── [Heuristic] Bus Factor:     {heu['bus_factor']} authors/file")
        print(f"└── [Heuristic] Top Coupling:   {heu['top_coupling']}")
        print("------------------------------------------")


def run_metrics_report():
    RepoMetrics().run_report()