import subprocess
from .. import config
from ..utils import cmd_runner


def get_all_commits(repo_path):
    """
    Retrieves the SHA-1 hashes of ALL commits in the repository (all branches, tags, and detached heads).
    Returns them in chronological order.
    """
    try:
        # git rev-list --all --reverse gives us the complete history graph
        cmd = ["git", "rev-list", "--all", "--reverse"]
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        # Split lines to get a list of hashes
        return result.stdout.strip().split('\n')
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Failed to list commits: {e}")
        return []


def run_rm_smoke_test():
    """
    Executes a Smoke Test for RefactoringMiner.
    FORCED MODE: Iterates through every commit explicitly to ensure 100% coverage.
    """
    print("--- ⚡ Starting RefactoringMiner Smoke Test (Whole History) ---")

    # 1. Define Output Path
    json_output = config.OUTPUTS_PATH / "refactorings.json"

    # Clear previous output if it exists (since we append in the loop)
    if json_output.exists():
        json_output.unlink()

    # 2. Get All Commits
    commits = get_all_commits(config.TOY_PROJECT_PATH)
    total_commits = len(commits)
    print(f"🎯 Target Analysis: {total_commits} commits found (including merges/detached).")

    success_count = 0

    # 3. Iterate and Execute
    for i, commit_hash in enumerate(commits):
        # Progress Log (e.g., [1/65])
        print(f"Processing {i + 1}/{total_commits}: {commit_hash[:7]}...")

        # Construct Command: ./RefactoringMiner -c <repo> <commit> -json <output>
        cmd = [
            str(config.RM_PATH),
            "-c",
            str(config.TOY_PROJECT_PATH),
            commit_hash,
            "-json",
            str(json_output)
        ]

        # Run silently (don't print stdout for every single commit to keep console clean)
        # We rely on the final file for validation
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            success_count += 1
        except subprocess.CalledProcessError:
            print(f"❌ Failed to analyze commit {commit_hash[:7]}")

    # 4. Final Verification
    if success_count > 0 and json_output.exists():
        print(f"✅ RefactoringMiner Success! Analyzed {success_count}/{total_commits} commits.")
        print(f"📄 Output saved to: {json_output.name}")
        return True
    else:
        print("❌ RefactoringMiner Failed (No output generated).")
        return False