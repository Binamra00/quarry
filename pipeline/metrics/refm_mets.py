import json
from pathlib import Path

try:
    from pydriller import Repository
except ImportError:
    print("⚠️ PyDriller not found. Churn metrics will be skipped.")
    Repository = None

from .. import config


def get_churn_map(repo_path):
    """
    Returns a dictionary mapping commit SHA to total churn (lines added + deleted).
    Used to cross-reference with RefactoringMiner output for 'Purity' analysis.
    """
    churn_map = {}
    if not Repository:
        return churn_map

    print(f"   ... ⏳ Mining churn data from {repo_path.name} for purity analysis ...")
    try:
        # Traverse all commits once to build the map
        for commit in Repository(str(repo_path)).traverse_commits():
            total_churn = 0
            for file in commit.modified_files:
                # We count churn for all files to check for 'noise' in the commit
                total_churn += file.added_lines + file.deleted_lines
            churn_map[commit.hash] = total_churn
    except Exception as e:
        print(f"   ⚠️ Error extracting churn: {e}")

    return churn_map


def calculate_refm_metrics(total_commits_mined=65):
    """
    Parses refactorings.json to calculate Refactoring Density and Refactoring Types.

    Args:
        total_commits_mined (int): Total commits analyzed (from repo_metrics).
                                   Defaults to 65 for toy project calibration.
    """
    json_path = config.OUTPUTS_PATH / "refactorings.json"

    if not json_path.exists():
        print("⚠️ Refactoring output not found. Skipping metrics.")
        return

    print("\n--- 📊 RefactoringMiner Metrics Report ---")

    # 0. Pre-fetch Churn Data for Purity Calculation
    churn_map = get_churn_map(config.TOY_PROJECT_PATH)

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)

        # 1. Basic Counts
        commits_list = data.get("commits", [])
        commits_with_refactorings = len(commits_list)

        # 2. Detailed Counts & Purity Analysis
        total_ops = 0
        refactoring_types = {}
        high_churn_refactorings = 0  # Potential "Impure" commits

        for commit in commits_list:
            refs = commit.get("refactorings", [])
            count = len(refs)
            total_ops += count

            # Purity Check: Get churn for this specific commit hash
            sha1 = commit.get("sha1")
            commit_churn = churn_map.get(sha1, 0)

            # HEURISTIC: If Churn > (Refactorings * 20), it might be a "Floss Refactoring" (Mixed)
            # 20 lines per refactoring is a generous buffer.
            if commit_churn > (count * 20):
                high_churn_refactorings += 1

            for r in refs:
                r_type = r.get("type", "Unknown")
                refactoring_types[r_type] = refactoring_types.get(r_type, 0) + 1

        # 3. Calculate Derived Metrics
        refactoring_density = (commits_with_refactorings / total_commits_mined) * 100 if total_commits_mined > 0 else 0
        avg_intensity = total_ops / commits_with_refactorings if commits_with_refactorings > 0 else 0

        # Purity Score: % of refactoring commits that are "Low Churn" (likely Atomic)
        clean_commits = commits_with_refactorings - high_churn_refactorings
        purity_score = (clean_commits / commits_with_refactorings) * 100 if commits_with_refactorings > 0 else 0

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

        # Sort and print top 5 types
        sorted_types = sorted(refactoring_types.items(), key=lambda x: x[1], reverse=True)
        for r_type, count in sorted_types[:5]:
            print(f"│   ├── {r_type}: {count}")

    except json.JSONDecodeError:
        print("❌ Error: refactorings.json is not valid JSON. (Did the tool crash mid-write?)")
    except Exception as e:
        print(f"❌ Error calculating metrics: {e}")


if __name__ == "__main__":
    calculate_refm_metrics()