import json
import statistics
from pathlib import Path
from pipeline import config


def calculate_pmd_metrics():
    """
    Parses PMD output to calculate Smell Density, Complexity Profile, and Hotspots.
    It combines data from 'pmd_candidates_*.json' (Numerator) and 'repo_metrics_*.json' (Denominator).
    """
    print("\n--- 📊 PMD Static Analysis Metrics Report ---")

    # 1. Resolve File Paths
    project_name = config.TOY_PROJECT_PATH.name
    pmd_json_path = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"
    repo_metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{project_name}.json"
    output_path = config.OUTPUTS_PATH / f"pmd_metrics_{project_name}.json"

    # 2. Load Data
    if not pmd_json_path.exists():
        print(f"⚠️ PMD output not found at: {pmd_json_path.name}")
        return

    if not repo_metrics_path.exists():
        print(f"⚠️ Repo metrics (for KLOC) not found at: {repo_metrics_path.name}")
        return

    try:
        with open(pmd_json_path, 'r') as f:
            pmd_data = json.load(f)

        with open(repo_metrics_path, 'r') as f:
            repo_data = json.load(f)

        # Extract Denominators
        # ideally we want 'current_sloc' here, but 'java_file_count' is a safe proxy
        # that we successfully mined in repo_mets.py
        file_count = repo_data.get("content", {}).get("java_file_count", 1)

    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON inputs: {e}")
        return

    # 3. Analyze Violations
    files = pmd_data.get("files", [])
    all_violations = []
    complexity_scores = []
    rule_counts = {}
    file_hotspots = {}

    for file_entry in files:
        fname = Path(file_entry.get("filename", "")).name
        violations = file_entry.get("violations", [])

        # Metric 2: Smell Intensity (Hotspots)
        # Store how many smells are in THIS specific file
        file_hotspots[fname] = len(violations)

        for v in violations:
            all_violations.append(v)

            # Metric 3: Rule Taxonomy
            rule = v.get("rule", "Unknown")
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

            # Metric 4: Method Complexity Mean
            # We look for the "CyclomaticComplexity" rule specifically
            if rule == "CyclomaticComplexity":
                # PMD description usually contains the score: "... has a cyclomatic complexity of 10."
                desc = v.get("description", "")
                try:
                    if "complexity of" in desc:
                        # Extract the last word and remove punctuation
                        score_str = desc.split("complexity of")[-1].strip(" .")
                        score = int(score_str)
                        complexity_scores.append(score)
                except ValueError:
                    pass

    # 4. Calculate Final Metrics
    total_smells = len(all_violations)

    # Metric 1: Smell Density (Smells per File)
    # Formula: Total Violations / Total Files in Repo
    smell_density_per_file = total_smells / file_count if file_count > 0 else 0

    # Metric 4: Complexity Stats
    if complexity_scores:
        avg_complexity = statistics.mean(complexity_scores)
        max_complexity = max(complexity_scores)
    else:
        avg_complexity = 0
        max_complexity = 0

    # 5. Save & Report
    metrics_output = {
        "scope": {
            "files_scanned": len(files),  # Files with at least 1 violation
            "total_repo_files": file_count,  # Total files in repo
            "total_smells_detected": total_smells
        },
        "density": {
            "smells_per_file": round(smell_density_per_file, 2)
        },
        "complexity_profile": {
            "average_cyclomatic_complexity": round(avg_complexity, 2),
            "max_cyclomatic_complexity": max_complexity,
            "methods_analyzed_for_complexity": len(complexity_scores)
        },
        "taxonomy": {
            "top_rules": dict(sorted(rule_counts.items(), key=lambda x: x[1], reverse=True))
        },
        "hotspots": {
            "top_smelly_files": dict(sorted(file_hotspots.items(), key=lambda x: x[1], reverse=True)[:5])
        }
    }

    with open(output_path, 'w') as f:
        json.dump(metrics_output, f, indent=2)

    print(f"📄 PMD metrics saved to: {output_path.name}")
    print(f"├── [Density]")
    print(f"│   ├── Total Smells: {total_smells}")
    print(f"│   └── Smells/File:  {smell_density_per_file:.2f}")
    print(f"│")
    print(f"├── [Complexity Profile]")
    print(f"│   ├── Avg Cyclomatic Complexity: {avg_complexity:.1f}")
    print(f"│   └── Max Complexity Found:      {max_complexity}")
    print(f"│")

    # [NEW] Explicitly Print Rule Taxonomy
    print(f"├── [Rule Taxonomy]")
    sorted_rules = sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)
    if sorted_rules:
        for rule, count in sorted_rules:
            print(f"│   ├── {rule}: {count}")
    else:
        print(f"│   └── (No violations found)")
    print(f"│")

    print(f"├── [Hotspots] (Top Files)")
    sorted_hotspots = sorted(file_hotspots.items(), key=lambda x: x[1], reverse=True)
    if sorted_hotspots:
        for f, count in sorted_hotspots[:3]:
            print(f"│   ├── {f}: {count} smells")
    else:
        print(f"│   └── (No hotspots found)")


if __name__ == "__main__":
    calculate_pmd_metrics()