import sys
import importlib.util
from pipeline import config
from pipeline import repo_metrics
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

    # Step 3: PMD Smoke Test
    print("\n--- Step 3: PMD Smoke Test ---")
    try:
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
    if rm_success and pmd_success:
        print("\n🎉 SMOKE TEST PASSED: All tools are operational.")
        sys.exit(0)
    else:
        print("\n⚠️ SMOKE TEST INCOMPLETE: Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()