import sys
import importlib.util
from pipeline import config
from pipeline import repo_metrics
# Import our new adapters
# NOTE: Using the specific names you created: refm_adapt and pmd_adapt
from pipeline.adapters import refm_adapt
from pipeline.adapters import pmd_adapt


def main():
    """
    Main Entry Point for the Smell-Ranker Pipeline.
    Currently configured for Phase 1: Component Verification (Smoke Test).
    """
    print("🚀 Starting Smell-Ranker Pipeline (Phase 1: Smoke Test)")
    print(f"📂 Configuration Loaded. Drive Path: {config.DRIVE_PATH}")

    # Step 1: Verification (Phase 0)
    # We run the metrics again to confirm the repo is accessible and healthy
    print("\n--- Step 1: Repository Verification ---")
    try:
        repo_metrics.run_metrics_report()
    except Exception as e:
        print(f"⚠️ Metrics calculation failed: {e}")
        # We don't stop here, we try to run the tools anyway

    # Step 2: RefactoringMiner Smoke Test (Your Task)
    print("\n--- Step 2: RefactoringMiner Smoke Test ---")
    try:
        rm_success = refm_adapt.run_rm_smoke_test()
    except AttributeError:
        print("⚠️ RefactoringMiner adapter function not found. Check function naming in refm_adapt.py")
        rm_success = False
    except Exception as e:
        print(f"❌ RefactoringMiner Exception: {e}")
        rm_success = False

    # Step 3: PMD Smoke Test (Darun's Task)
    print("\n--- Step 3: PMD Smoke Test ---")
    try:
        # We wrap this in a try/except specifically for NotImplementedError or missing attributes
        # so the pipeline doesn't crash while Darun is still working on it.
        pmd_success = pmd_adapt.run_pmd_smoke_test()
    except AttributeError:
        print("⚠️ PMD adapter function not implemented yet (Waiting for Darun).")
        pmd_success = False
    except Exception as e:
        print(f"❌ PMD Exception: {e}")
        pmd_success = False

    # Step 4: Final Status
    print("\n--- 🏁 Pipeline Completion Report ---")

    if rm_success:
        print("✅ RefactoringMiner: OPERATIONAL")
    else:
        print("❌ RefactoringMiner: FAILED (or Pending)")

    if pmd_success:
        print("✅ PMD: OPERATIONAL")
    else:
        print("❌ PMD: FAILED (or Pending)")

    # Logic for Exit Codes (Useful for CI/CD or Shell Scripts)
    # We exit with 0 only if BOTH are successful (or if we decide partially working is okay for now)
    if rm_success and pmd_success:
        print("\n🎉 SMOKE TEST PASSED: All tools are operational.")
        sys.exit(0)
    else:
        print("\n⚠️ SMOKE TEST INCOMPLETE: Check logs above.")
        # We assume failure for now to alert us to missing pieces
        sys.exit(1)


if __name__ == "__main__":
    main()