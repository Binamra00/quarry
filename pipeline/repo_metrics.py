import os
from collections import defaultdict, Counter
from pathlib import Path

try:
    from pydriller import Repository
except ImportError:
    print("CRITICAL ERROR: PyDriller not installed. Run '!pip install pydriller' in Colab.")
    raise

from . import config  # Assumes pipeline/config.py exists and has TOY_PROJECT_PATH

# --- HEURISTIC KEYWORDS ---
FIX_KEYWORDS = ['fix', 'bug', 'issue', 'close', 'resolv', 'crash', 'fail', 'error', 'defect']
REFACTOR_KEYWORDS = ['refactor', 'cleanup', 'clean up', 'rename', 'move', 'extract', 'restruct', 'optimiz']


def analyze_repo_metrics(repo_path):
    """
    Mines the repository using PyDriller to extract Phase 0 heuristics.
    """
    print(f"--- ⛏️ Mining Phase 0 Metrics for: {repo_path.name} ---")

    # 1. Initialize Counters
    stats = {
        "total_commits": 0,
        "fix_commits": 0,
        "refactor_commits": 0,
        "file_types": Counter(),
        "authors": set(),
        "start_date": None,
        "end_date": None,
        "total_churn": 0
    }

    file_authors = defaultdict(set)
    pair_coupling = Counter()

    # 2. Iterate through Commits (The Mining Step)
    # traverse_commits() is a generator, so it processes one by one (memory efficient)
    for commit in Repository(str(repo_path)).traverse_commits():
        stats["total_commits"] += 1
        stats["authors"].add(commit.author.name)

        # A. Date Tracking
        if stats["start_date"] is None:
            stats["start_date"] = commit.committer_date
        stats["end_date"] = commit.committer_date

        # B. Message Analysis (Heuristics)
        msg_lower = commit.msg.lower()
        if any(kw in msg_lower for kw in FIX_KEYWORDS):
            stats["fix_commits"] += 1
        if any(kw in msg_lower for kw in REFACTOR_KEYWORDS):
            stats["refactor_commits"] += 1

        # C. File Analysis
        modified_java_files = []
        for file in commit.modified_files:
            # Global File Type Count (count every file touched)
            ext = os.path.splitext(file.filename)[1] if file.filename else ".no_ext"
            stats["file_types"][ext] += 1

            if file.filename.endswith('.java'):
                modified_java_files.append(file.filename)

                # Churn = Added + Deleted (Lines modified count as both add+del in git)
                churn = file.added_lines + file.deleted_lines
                stats["total_churn"] += churn

                # Ownership (Bus Factor tracking)
                file_authors[file.filename].add(commit.author.name)

        # D. Coupling Analysis (Files changed together)
        if len(modified_java_files) > 1:
            modified_java_files.sort()
            # Create pairs of all files in this commit
            for i in range(len(modified_java_files)):
                for j in range(i + 1, len(modified_java_files)):
                    pair = (modified_java_files[i], modified_java_files[j])
                    pair_coupling[pair] += 1

    return stats, file_authors, pair_coupling


def run_metrics_report():
    """Generates and prints the project statistics in Tree Format."""
    repo = config.TOY_PROJECT_PATH

    if not repo.exists():
        print(f"Error: Repository not found at {repo}")
        return

    # Run the Mining
    stats, file_authors, pair_coupling = analyze_repo_metrics(repo)

    # Calculate Aggregates
    if stats["total_commits"] > 0:
        project_age_days = (stats["end_date"] - stats["start_date"]).days
        avg_churn = stats["total_churn"] / stats["total_commits"]
        fix_ratio = (stats["fix_commits"] / stats["total_commits"]) * 100
        refactor_ratio = (stats["refactor_commits"] / stats["total_commits"]) * 100
    else:
        project_age_days = 0
        avg_churn = 0
        fix_ratio = 0
        refactor_ratio = 0

    # Bus Factor: Average number of unique authors per file
    avg_bus_factor = sum(len(a) for a in file_authors.values()) / len(file_authors) if file_authors else 0

    # Top Coupled Pair
    top_coupled = pair_coupling.most_common(1)
    if top_coupled:
        top_pair_name = f"{Path(top_coupled[0][0][0]).name} + {Path(top_coupled[0][0][1]).name}"
        top_pair_count = top_coupled[0][1]
    else:
        top_pair_name = "None"
        top_pair_count = 0

    # Main File Type
    top_file_type = stats["file_types"].most_common(1)
    main_lang = top_file_type[0][0] if top_file_type else "Unknown"

    # --- PRINT REPORT ---
    print("\n--- Project Metrics Analysis (Phase 0) ---")
    print(f"Project: {repo.name}")
    print(f"├── [History] Total Commits:    {stats['total_commits']}")
    print(f"├── [History] Age (Days):       {project_age_days} days")
    print(f"│")
    print(f"├── [Content] Main Language:    {main_lang}")
    print(f"├── [Content] Java Files:       {len(file_authors)}")
    print(f"├── [Content] Total Churn:      {stats['total_churn']} lines (Avg {avg_churn:.1f}/commit)")
    print(f"│")
    print(f"├── [Heuristic] Bug-Fixes:      {stats['fix_commits']} ({fix_ratio:.1f}%)")
    print(f"├── [Heuristic] Refactorings:   {stats['refactor_commits']} ({refactor_ratio:.1f}%)")
    print(f"├── [Heuristic] Bus Factor:     {avg_bus_factor:.2f} authors/file")
    print(f"└── [Heuristic] Top Coupling:   {top_pair_name} ({top_pair_count} shared commits)")
    print("------------------------------------------\n")


if __name__ == "__main__":
    run_metrics_report()