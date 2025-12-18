import subprocess
import json
import os
from pipeline import config


def run_pmd_smoke_test():
    """
    Executes PMD using a CUSTOM 'pmd_rules_00.xml'.
    Includes robust debugging for JSON errors and pre-flight checks.
    """
    print("--- 🔍 Starting PMD Static Analysis (Targeted Rules) ---")

    # 1. Setup Paths
    ruleset_path = config.REPO_ROOT / "pipeline" / "rulesets" / "pmd_rules_00.xml"
    project_name = config.TOY_PROJECT_PATH.name
    output_json = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"
    pmd_executable = config.PMD_PATH

    # 2. Pre-Flight Checks
    if not ruleset_path.exists():
        print(f"❌ Error: Custom ruleset not found at {ruleset_path}")
        return False

    if not pmd_executable.exists():
        print(f"❌ Error: PMD executable not found at {pmd_executable}")
        return False

    if not os.access(pmd_executable, os.X_OK):
        print(f"⚠️ Warning: PMD binary at {pmd_executable} is not executable. Attempting to fix...")
        try:
            os.chmod(pmd_executable, 0o755)
            print("   ✅ Permissions fixed.")
        except Exception as e:
            print(f"   ❌ Failed to set permissions: {e}")
            return False

    # 3. Construct Command
    cmd = [
        str(pmd_executable),
        "check",
        "-d", str(config.TOY_PROJECT_PATH),
        "-R", str(ruleset_path),
        "-f", "json",
        "-r", str(output_json),
        "--no-cache"
    ]

    print(f"   Target: {config.TOY_PROJECT_PATH.name}")
    print(f"   Ruleset: {ruleset_path.name}")
    print(f"   Command: {' '.join(cmd)}")  # Print the exact command for debugging

    try:
        # Run PMD
        result = subprocess.run(cmd, capture_output=True, text=True)

        if output_json.exists():
            # Validate JSON content
            if output_json.stat().st_size == 0:
                print("❌ PMD Failed: Output file created but is EMPTY.")
                print(f"STDERR Log (Why did it fail?):\n{result.stderr}")
                print(f"STDOUT Log:\n{result.stdout}")
                return False

            try:
                with open(output_json, 'r') as f:
                    data = json.load(f)
            except json.JSONDecodeError as je:
                print(f"❌ PMD Failed: Output file contains invalid JSON.")
                print(f"JSON Error: {je}")
                # Print raw file content for inspection
                with open(output_json, 'r') as f:
                    print(f"File Raw Content:\n{f.read(500)}")
                print(f"STDERR Log:\n{result.stderr}")
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
            print(f"STDERR: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ PMD Execution Failed (Python Exception): {e}")
        return False