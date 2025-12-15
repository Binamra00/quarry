from .. import config
from ..utils import cmd_runner


def run_rm_smoke_test():
    """
    Executes a Smoke Test for RefactoringMiner.
    Runs the tool against the 'toy_project' and saves the JSON output.
    """
    print("--- ⚡ Starting RefactoringMiner Smoke Test ---")

    # 1. Define Output Path
    json_output = config.OUTPUTS_PATH / "refactorings.json"

    # 2. Construct Command
    # RefactoringMiner -a <git-repo-folder> <branch> -json <output-path>
    cmd = [
        str(config.RM_PATH),  # The executable
        "-a",  # Analyze all commits
        str(config.TOY_PROJECT_PATH),  # The target repo
        "master",  # The branch (toy repo uses master)
        "-json",  # Output format
        str(json_output)  # Output file
    ]

    # 3. Execute
    success, output = cmd_runner.run_command(cmd, working_dir=config.DRIVE_PATH)

    if success:
        print(f"✅ RefactoringMiner Success! Output saved to: {json_output.name}")
    else:
        print("❌ RefactoringMiner Failed.")

    return success