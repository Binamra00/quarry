import json
import os
from pipeline import config
from pipeline.utils import cmd_subprocess


def run_pmd_smoke_test():
    """
    Executes PMD using a CUSTOM 'pmd_rules_00.xml'.
    Uses the unified cmd_subprocess for execution safety.
    """
    print("--- 🔍 Starting PMD Static Analysis (Targeted Rules) ---")

    # 1. Setup Paths
    ruleset_path = config.PMD_RULESET_PATH
    project_name = config.TOY_PROJECT_PATH.name
    output_json = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"

    # 2. Pre-Flight Checks
    if not ruleset_path.exists():
        print(f"❌ Error: Custom ruleset not found at {ruleset_path}")
        return False

    if not config.PMD_PATH.exists():
        print(f"❌ Error: PMD executable not found at {config.PMD_PATH}")
        return False

    # 3. Construct Command
    # Note: We use str() on paths to ensure compatibility
    cmd = [
        str(config.PMD_PATH),
        "check",
        "-d", str(config.TOY_PROJECT_PATH),
        "-R", str(ruleset_path),
        "-f", "json",
        "-r", str(output_json),
        "--no-cache"
    ]

    print(f"   Target: {project_name}")
    print(f"   Ruleset: {ruleset_path.name}")

    # 4. Execute via Unified Runner
    # PMD Exit Codes: 0 = Clean, 4 = Violations Found, 1 = Error
    success, output = cmd_subprocess.run_command(
        cmd,
        allowed_exit_codes=[0, 4]
    )

    if not success:
        print("❌ PMD execution failed (See logs above).")
        return False

    # 5. Output Verification
    if output_json.exists():
        # Validate JSON content
        if output_json.stat().st_size == 0:
            print("❌ PMD Failed: Output file created but is EMPTY.")
            return False

        try:
            with open(output_json, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as je:
            print(f"❌ PMD Failed: Output file contains invalid JSON.")
            print(f"   Error: {je}")
            return False

        files = data.get("files", [])
        total_violations = 0
        for file in files:
            total_violations += len(file.get("violations", []))

        print(f"✅ PMD Analysis Complete!")
        print(f"   Total Target Smells Found: {total_violations}")
        print(f"📄 Output saved to: {output_json.name}")
        return True
    else:
        print("❌ PMD Failed: No output file generated.")
        return False