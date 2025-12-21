import json
import tempfile
import subprocess
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
# [NEW] Import the UI helper we just built
from pipeline.utils import ui_strategy
from pipeline.adapters.i_adapter import IAdapter


class RefactoringMinerAdapter(IAdapter):
    """
    Adapter for RefactoringMiner v3.0.
    Strategy: 'Forced-Loop' with 'Temp-to-Persistent' I/O.
    """

    def get_tool_name(self) -> str:
        return "RefactoringMiner (History Mining)"

    def get_output_path(self) -> Path:
        project_name = config.TOY_PROJECT_PATH.name
        return config.OUTPUTS_PATH / f"refactorings_{project_name}.json"

    def _get_all_commits(self, repo_path: Path) -> List[str]:
        """Helper: Retrieves SHA-1 hashes of commits modifying .java files."""
        cmd = ["git", "rev-list", "--all", "--reverse", "--", "*.java"]
        success, output = adapter_subprocess.run_command(cmd, cwd=str(repo_path))

        if success and output:
            return output.strip().split('\n')
        else:
            print("⚠️ Failed to list commits or no Java commits found.")
            return []

    def execute(self) -> bool:
        print(f"--- ⚡ Starting {self.get_tool_name()} ---")

        final_json_path = self.get_output_path()
        log_path = self.get_log_path()

        commits = self._get_all_commits(config.TOY_PROJECT_PATH)
        total_commits = len(commits)

        if total_commits == 0:
            print("❌ No commits found to analyze.")
            return False

        print(f"🎯 Target Analysis: {total_commits} commits found.")
        print(f"   📝 Logging raw output to: {log_path.name}")

        all_refactorings = []
        success_count = 0

        with open(log_path, "w") as log_file:
            log_file.write(f"--- RefactoringMiner Log: {config.TOY_PROJECT_PATH.name} ---\n")

            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)
                print(f"   [Performance] Using temporary local buffer: {temp_dir}")

                for i, commit_hash in enumerate(commits):
                    # [FIXED] Delegate the display logic to the agnostic UI utility
                    ui.update_progress(i + 1, total_commits, prefix="   ⏳ Progress:")

                    temp_json_path = temp_dir / f"commit_{commit_hash}.json"

                    cmd = [
                        str(config.RM_PATH), "-c", str(config.TOY_PROJECT_PATH),
                        commit_hash, "-json", str(temp_json_path)
                    ]

                    try:
                        log_file.write(f"\n[COMMIT {commit_hash}] ----------------\n")
                        log_file.flush()

                        subprocess_result = subprocess.run(
                            cmd,
                            stdout=log_file,
                            stderr=subprocess.STDOUT,
                            text=True,
                            check=False
                        )

                        if subprocess_result.returncode == 0 and temp_json_path.exists():
                            try:
                                with open(temp_json_path, 'r') as f:
                                    data = json.load(f)
                                    if "commits" in data:
                                        all_refactorings.extend(data["commits"])
                                success_count += 1
                            except json.JSONDecodeError:
                                log_file.write(f"[ERROR] Invalid JSON for {commit_hash}\n")
                        else:
                            log_file.write(f"[ERROR] Non-zero exit or missing output for {commit_hash}\n")

                    except Exception as e:
                        log_file.write(f"[EXCEPTION] {e}\n")

        # Clear the progress line for a clean finish
        ui.clear_line()

        # Final Report
        print(f"   Processed {total_commits} commits.")
        print(f"   💾 Saving results to: {final_json_path.name}")
        try:
            with open(final_json_path, 'w') as f:
                json.dump({"commits": all_refactorings}, f, indent=2)

            print(f"✅ {self.get_tool_name()} Success! Analyzed {success_count}/{total_commits} commits.")
            return True
        except Exception as e:
            print(f"❌ Failed to save final output: {e}")
            return False