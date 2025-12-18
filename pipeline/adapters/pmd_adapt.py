import subprocess
import json
from ..config import config # Standard import

def run_pmd_smoke_test():
    """
    Executes PMD using a CUSTOM 'pmd_rules_00.xml'.
    Includes robust debugging for JSON errors.
    """
    print("--- 🔍 Starting PMD Static Analysis (Targeted Rules) ---")

    # 1. Setup Paths
    ruleset_path = config.REPO_ROOT / "pipeline" / "rulesets" / "pmd_rules_00.xml"
    project_name = config.TOY_PROJECT_PATH.name
    output_json = config.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"

    # 2. Check if Ruleset Exists
    if not ruleset_path.exists():
        print(f"❌ Error: Custom ruleset not found at {ruleset_path}")
        return False

    # 3. Construct Command
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

    try:
        # Run PMD
        result = subprocess.run(cmd, capture_output=True, text=True)

        if output_json.exists():
            # Validate JSON content
            if output_json.stat().st_size == 0:
                print("❌ PMD Failed: Output file created but is EMPTY.")
                print(f"STDERR Log:\n{result.stderr}")
                return False

            try:
                with open(output_json, 'r') as f:
                    data = json.load(f)
            except json.JSONDecodeError as je:
                print(f"❌ PMD Failed: Output file contains invalid JSON.")
                print(f"JSON Error: {je}")
                print(f"STDERR Log (Check for Ruleset Errors):\n{result.stderr}")
                # Optional: Print the first few lines of the file to see what it wrote
                with open(output_json, 'r') as f:
                    print(f"File Content Preview:\n{f.read(200)}...")
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
        print(f"❌ PMD Execution Failed: {e}")
        return False