import json
from pathlib import Path
from pipeline import config
from pipeline.utils import cmd_subprocess
from pipeline.adapters.i_adapter import IAdapter


class PMDAdapter(IAdapter):
    """
    Adapter for PMD Static Analyzer v7.18.0.
    Strategy: Snapshot Analysis using Custom Ruleset.
    """

    def get_tool_name(self) -> str:
        return "PMD Static Analysis"

    def get_output_path(self) -> Path:
        project_name = config.TOY_PROJECT_PATH.name
        return config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"

    def execute(self) -> bool:
        print(f"--- 🔍 Starting {self.get_tool_name()} ---")

        # Setup
        ruleset_path = config.PMD_RULESET_PATH
        output_json = self.get_output_path()
        log_path = self.get_log_path()

        # Pre-Flight Checks
        if not ruleset_path.exists():
            print(f"❌ Error: Custom ruleset not found at {ruleset_path}")
            return False

        if not config.PMD_PATH.exists():
            print(f"❌ Error: PMD executable not found at {config.PMD_PATH}")
            return False

        # Command Construction
        cmd = [
            str(config.PMD_PATH),
            "check",
            "-d", str(config.TOY_PROJECT_PATH),
            "-R", str(ruleset_path),
            "-f", "json",
            "-r", str(output_json),
            "--no-cache"
        ]

        print(f"   Target: {config.TOY_PROJECT_PATH.name}")
        print(f"   Ruleset: {ruleset_path.name}")

        # Pass the log_path to the runner
        success, _ = cmd_subprocess.run_command(
            cmd,
            allowed_exit_codes=[0, 4],
            log_file_path=log_path
        )

        if not success:
            print("❌ PMD execution failed.")
            return False

        # Verification
        if output_json.exists() and output_json.stat().st_size > 0:
            try:
                with open(output_json, 'r') as f:
                    data = json.load(f)
                    file_count = len(data.get("files", []))
                    print(f"✅ PMD Complete. Scanned {file_count} files with violations.")
                    print(f"📄 Output saved to: {output_json.name}")
                    return True
            except json.JSONDecodeError:
                print("❌ PMD Failed: Invalid JSON output.")
                return False
        else:
            print("❌ PMD Failed: No output generated.")
            return False