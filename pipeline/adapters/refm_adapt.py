import json
import tempfile
import os
from pathlib import Path
from pipeline import config
from pipeline.utils import cmd_subprocess


def get_all_commits(repo_path):
    """
    Retrieves the SHA-1 hashes of commits that modified Java files.
    """
    # Uses raw git command because PyDriller is slower for simple hash retrieval
    cmd = ["git", "rev-list", "--all", "--reverse", "--", "*.java"]

    # We use cmd_subprocess here too for consistency
    success, output = cmd_subprocess.run_command(cmd, cwd=repo_path)

    if success and output:
        return output.strip().split('\n')
    else:
        print("⚠️ Failed to list commits or no Java commits found.")
        return []


def run_refm_smoke_test():
    """
    Executes RefactoringMiner using the 'Forced-Loop' strategy.

    🚀 PERFORMANCE FIX:
    Uses a 'Temp-to-Persistent' I/O strategy.
    1. Writes RM output to a local temp folder (Fast I/O).
    2. Reads into memory immediately.
    3. Writes to Drive ONLY ONCE at the end (1 write vs 5000 writes).
    """
    print("--- ⚡ Starting RefactoringMiner Smoke Test (Whole History) ---")

    # 1. Define Final Output Path (Persistent Drive/Local)
    project_name = config.TOY_PROJECT_PATH.name
    final_json_path = config.OUTPUTS_PATH / f"refactorings_{project_name}.json"

    # 2. Get All Commits
    commits = get_all_commits(config.TOY_PROJECT_PATH)
    total_commits = len(commits)

    if total_commits == 0:
        print("❌ No commits found to analyze.")
        return False

    print(f"🎯 Target Analysis: {total_commits} commits found (including merges/detached).")

    all_refactorings = []
    success_count = 0

    # 3. Create a Temporary Directory for fast I/O
    # This folder lives in /tmp (or local OS temp), NOT on Google Drive
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        print(f"   [Performance] Using temporary local buffer: {temp_dir}")

        # 4. Iterate and Execute
        for i, commit_hash in enumerate(commits):
            # Progress Log (e.g., [1/40])
            print(f"Processing {i + 1}/{total_commits}: {commit_hash[:7]}...")

            # Define temp file for THIS commit
            temp_json_path = temp_dir / f"commit_{commit_hash}.json"

            cmd = [
                str(config.RM_PATH),
                "-c",
                str(config.TOY_PROJECT_PATH),
                commit_hash,
                "-json",
                str(temp_json_path)
            ]

            # Execute via Unified Runner
            success, _ = cmd_subprocess.run_command(cmd)

            if success:
                # Read the temp file into memory immediately
                if temp_json_path.exists():
                    try:
                        with open(temp_json_path, 'r') as f:
                            data = json.load(f)
                            # RefactoringMiner outputs {"commits": [...]}. We extract the list.
                            if "commits" in data:
                                all_refactorings.extend(data["commits"])
                        success_count += 1
                    except json.JSONDecodeError:
                        pass  # Empty or invalid JSON is ignored
            else:
                print(f"❌ Failed to analyze commit {commit_hash[:7]}")

    # 5. Final Save (The ONLY write to Google Drive)
    print(f"   💾 Saving aggregated results to persistent storage...")
    final_data = {"commits": all_refactorings}

    try:
        with open(final_json_path, 'w') as f:
            json.dump(final_data, f, indent=2)
    except Exception as e:
        print(f"❌ Failed to save final output to Drive: {e}")
        return False

    # 6. Verification
    if success_count > 0 and final_json_path.exists():
        print(f"✅ RefactoringMiner Success! Analyzed {success_count}/{total_commits} commits.")
        print(f"📄 Output saved to: {final_json_path.name}")
        return True
    else:
        print("❌ RefactoringMiner Failed (No output generated).")
        return False