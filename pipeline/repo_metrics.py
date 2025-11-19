import subprocess
from pathlib import Path
from . import config


def count_commits(repo_path):
    """Counts total commits in the repository."""
    try:
        # git rev-list --count HEAD gives the total number of commits
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return int(result.stdout.strip())
    except subprocess.CalledProcessError:
        return 0


def count_java_files(repo_path):
    """Counts the number of .java files."""
    return len(list(repo_path.rglob("*.java")))


def count_loc(repo_path):
    """Approximates Lines of Code (LOC) by counting lines in all .java files."""
    total_lines = 0
    for java_file in repo_path.rglob("*.java"):
        try:
            with open(java_file, 'r', encoding='utf-8', errors='ignore') as f:
                total_lines += sum(1 for _ in f)
        except Exception:
            pass
    return total_lines


def run_metrics_report():
    """Generates and prints the project statistics."""
    print("\n--- 📊 Project Metrics Analysis ---")
    repo = config.TOY_PROJECT_PATH

    if not repo.exists():
        print(f"❌ Error: Repository not found at {repo}")
        return

    commits = count_commits(repo)
    files = count_java_files(repo)
    loc = count_loc(repo)
    kloc = loc / 1000.0

    print(f"Project: {repo.name}")
    print(f"├── Total Commits: {commits}")
    print(f"├── Java Files:    {files}")
    print(f"├── Total LOC:     {loc}")
    print(f"└── KLOC:          {kloc:.2f}")
    print("-----------------------------------\n")


if __name__ == "__main__":
    run_metrics_report()