import subprocess
import json
from .. import rulesets


def run_pmd_smoke_test():
    """
    Executes PMD using a CUSTOM 'pmd_rules_00.xml' that references standard rules.
    This is efficient (runs only what we need) but scientifically valid (uses standard definitions).
    """
    print("--- 🔍 Starting PMD Static Analysis (Targeted Rules) ---")

    # 1. Setup Paths
    # UPDATED: Looking for 'pmd_rules_00.xml' instead of 'design.xml'
    ruleset_path = rulesets.REPO_ROOT / "pipeline" / "rulesets" / "pmd_rules_00.xml"

    # Dynamic output name based on project
    project_name = rulesets.TOY_PROJECT_PATH.name
    output_json = rulesets.OUTPUTS_PATH / f"pmd_candidates_{project_name}.json"

    # 2. Check if Ruleset Exists
    if not ruleset_path.exists():
        print(f"❌ Error: Custom ruleset not found at {ruleset_path}")
        print("   Please create the XML file in pipeline/rulesets/pmd_rules_00.xml")
        return False

    # 3. Construct Command
    cmd = [
        str(rulesets.PMD_PATH),
        "check",
        "-d", str(rulesets.TOY_PROJECT_PATH),
        "-R", str(ruleset_path),  # Use our efficient custom file
        "-f", "json",
        "-r", str(output_json),
        "--no-cache"
    ]

    print(f"   Target: {rulesets.TOY_PROJECT_PATH.name}")
    print(f"   Ruleset: {ruleset_path.name}")

    try:
        # Run PMD
        result = subprocess.run(cmd, capture_output=True, text=True)

        if output_json.exists():
            # Validate JSON content
            with open(output_json, 'r') as f:
                data = json.load(f)

            files = data.get("files", [])
            total_violations = 0

            # Since our XML ONLY contains the rules we want,
            # every violation found is a target smell.
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