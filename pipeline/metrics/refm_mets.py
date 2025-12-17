import json

try:
    from pydriller import Repository
except ImportError:
    print("⚠️ PyDriller not found. Churn metrics will be skipped.")
    Repository = None

from .. import config


def get_churn_map(repo_path):
    """
    Returns a dictionary mapping commit SHA to total churn.
    """
    churn_map = {}
    if not Repository:
        return churn_map

    print(f"   ... ⏳ Mining churn data from {repo_path.name} for purity analysis ...")
    try:
        for commit in Repository(str(repo_path)).traverse_commits():
            total_churn = 0
            for file in commit.modified_files:
                total_churn += file.added_lines + file.deleted_lines
            churn_map[commit.hash] = total_churn
    except Exception as e:
        print(f"   ⚠️ Error extracting churn: {e}")

    return churn_map


def calculate_refm_metrics(total_commits_mined=65):
    """
    Calculates metrics, SAVES to JSON, and prints to console.
    """
    # Dynamic filenames based on project name
    project_name = config.TOY_PROJECT_PATH.name
    json_path = config.OUTPUTS_PATH / "refactorings.json"
    metric_output_path = config.OUTPUTS_PATH / f"refactoring_metrics_{project_name}.json"

    if not json_path.exists():
        print("⚠️ Refactoring output not found. Skipping metrics.")
        return

    print("\n--- 📊 RefactoringMiner Metrics Report ---")

    churn_map = get_churn_map(config.TOY_PROJECT_PATH)

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)

        commits_list = data.get("commits", [])
        commits_with_refactorings = len(commits_list)

        total_ops = 0
        refactoring_types = {}
        high_churn_refactorings = 0

        for commit in commits_list:
            refs = commit.get("refactorings", [])
            count = len(refs)
            total_ops += count

            sha1 = commit.get("sha1")
            commit_churn = churn_map.get(sha1, 0)

            # Purity Heuristic: > 20 lines of churn per refactoring op = High Churn
            if commit_churn > (count * 20):
                high_churn_refactorings += 1

            for r in refs:
                r_type = r.get("type", "Unknown")
                refactoring_types[r_type] = refactoring_types.get(r_type, 0) + 1

        # --- Calculations ---
        refactoring_density = (commits_with_refactorings / total_commits_mined) * 100 if total_commits_mined > 0 else 0
        avg_intensity = total_ops / commits_with_refactorings if commits_with_refactorings > 0 else 0
        clean_commits = commits_with_refactorings - high_churn_refactorings
        purity_score = (clean_commits / commits_with_refactorings) * 100 if commits_with_refactorings > 0 else 0

        # --- SAVE TO JSON ---
        sorted_types = sorted(refactoring_types.items(), key=lambda x: x[1], reverse=True)

        metrics_data = {
            "scope": {
                "total_commits_history": total_commits_mined,
                "commits_with_refactorings": commits_with_refactorings,
                "refactoring_density_percent": round(refactoring_density, 2)
            },
            "signal_strength": {
                "total_operations": total_ops,
                "avg_ops_per_commit": round(avg_intensity, 2)
            },
            "purity": {
                "high_churn_commits": high_churn_refactorings,
                "clean_commits": clean_commits,
                "purity_score_percent": round(purity_score, 2)
            },
            "top_types": {k: v for k, v in sorted_types[:10]}
        }

        with open(metric_output_path, 'w') as f:
            json.dump(metrics_data, f, indent=2)
        print(f"📄 Calculated metrics saved to: {metric_output_path.name}")

        # --- PRINT REPORT ---
        print(f"├── [Dataset Scope]")
        print(f"│   ├── Total Commits Analyzed: {total_commits_mined}")
        print(f"│   ├── Commits w/ Refactorings: {commits_with_refactorings}")
        print(f"│   └── Refactoring Density:    {refactoring_density:.1f}% (Target: >40%)")
        print(f"│")
        print(f"├── [Signal Strength]")
        print(f"│   ├── Total Refactoring Ops:  {total_ops}")
        print(f"│   └── Avg Ops per Commit:     {avg_intensity:.1f}")
        print(f"│")
        print(f"├── [Dataset Purity] (Atomic vs. Floss)")
        print(f"│   ├── Total Churn Mapped:     {len(churn_map)} commits")
        print(f"│   ├── Likely 'Floss' Commits: {high_churn_refactorings} (High churn relative to ops)")
        print(f"│   └── Commit Purity Score:    {purity_score:.1f}% (Target: >80%)")
        print(f"│")
        print(f"├── [Top Refactoring Types] (Heuristic Inputs)")
        for r_type, count in sorted_types[:5]:
            print(f"│   ├── {r_type}: {count}")

    except json.JSONDecodeError:
        print("❌ Error: refactorings.json is not valid JSON.")
    except Exception as e:
        print(f"❌ Error calculating metrics: {e}")


if __name__ == "__main__":
    calculate_refm_metrics()