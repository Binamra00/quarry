import subprocess
import json
from .. import config

# Removed unused import: from ..utils import cmd_runner

def get_all_commits(repo_path):
    """
    Retrieves the SHA-1 hashes of commits that modified Java files.
    """
    try:
        # Added '--', '*.java' to filter only relevant commits
        cmd = ["git", "rev-list", "--all", "--reverse", "--", "*.java"]
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().split('\n')
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Failed to list commits: {e}")
        return []


def run_refm_smoke_test():
    """
    Executes a Smoke Test for RefactoringMiner.
    FORCED MODE: Iterates through every commit explicitly, accumulates results,
    and writes a valid JSON list at the end.
    """
    print("--- ⚡ Starting RefactoringMiner Smoke Test (Whole History) ---")

    # 1. Define Output Path
    json_output_path = config.OUTPUTS_PATH / "refactorings.json"

    # 2. Get All Commits
    commits = get_all_commits(config.TOY_PROJECT_PATH)
    total_commits = len(commits)
    print(f"🎯 Target Analysis: {total_commits} commits found (including merges/detached).")

    all_refactorings = []
    success_count = 0

    # 3. Iterate and Execute
    for i, commit_hash in enumerate(commits):
        # Progress Log (e.g., [1/65])
        print(f"Processing {i + 1}/{total_commits}: {commit_hash[:7]}...")

        # We use a temporary file for each commit to avoid overwrite issues
        temp_json = config.OUTPUTS_PATH / "temp_refm.json"

        cmd = [
            str(config.RM_PATH),
            "-c",
            str(config.TOY_PROJECT_PATH),
            commit_hash,
            "-json",
            str(temp_json)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)

            # Read the temp file and append data to our main list
            if temp_json.exists():
                with open(temp_json, 'r') as f:
                    try:
                        data = json.load(f)
                        # RefactoringMiner outputs a dict with "commits": [...]
                        # We want to flatten this into a single list of commit objects
                        if "commits" in data:
                            all_refactorings.extend(data["commits"])
                    except json.JSONDecodeError:
                        pass  # Empty or invalid JSON

                temp_json.unlink()  # Cleanup temp file

            success_count += 1
        except subprocess.CalledProcessError:
            print(f"❌ Failed to analyze commit {commit_hash[:7]}")

    # 4. Final Save
    # We wrap the list in a "commits" key to match RM's standard format
    final_data = {"commits": all_refactorings}

    with open(json_output_path, 'w') as f:
        json.dump(final_data, f, indent=2)

    # 5. Verification
    if success_count > 0 and json_output_path.exists():
        print(f"✅ RefactoringMiner Success! Analyzed {success_count}/{total_commits} commits.")
        print(f"📄 Output saved to: {json_output_path.name}")
        return True
    else:
        print("❌ RefactoringMiner Failed (No output generated).")
        return False