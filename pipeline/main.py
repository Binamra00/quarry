import sys
import importlib
from pipeline import config
from pipeline.metrics import refm_mets, repo_mets

# NOTE: We import adapters inside the functions or try/except blocks
# to prevent the script from crashing if a team member's file (e.g., pmd_adapt)
# is missing or has a syntax error.

def main():
    """
    Main Entry Point for the Smell-Ranker Pipeline.
    Currently configured for Phase 1: Component Verification (Smoke Test).
    """
    print("🚀 Starting Smell-Ranker Pipeline (Phase 1: Smoke Test)")
    print(f"📂 Configuration Loaded. Drive Path: {config.DRIVE_PATH}")

    # Step 1: Verification (Phase 0)
    print("\n--- Step 1: Repository Verification ---")
    repo_total_commits = 0
    try:
        # Capture the actual commit count to pass to refm_mets later
        repo_total_commits = repo_mets.run_metrics_report()
    except Exception as e:
        print(f"⚠️ Metrics calculation failed: {e}")

    # Step 2: RefactoringMiner Smoke Test
    print("\n--- Step 2: RefactoringMiner Smoke Test ---")
    rm_success = False
    try:
        # Import inside the try block to catch ImportErrors safely
        from pipeline.adapters import refm_adapt
        rm_success = refm_adapt.run_refm_smoke_test()
    except ImportError:
         print("⚠️ refm_adapt module not found. Check pipeline/adapters/ folder.")
    except Exception as e:
        print(f"❌ RefactoringMiner Exception: {e}")

    # Step 3: PMD Static Analysis (Phase 2)
    print("\n--- Step 3: PMD Smoke Test ---")
    pmd_success = False
    try:
        from pipeline.adapters import pmd_adapt
        # Now fully implemented
        pmd_success = pmd_adapt.run_pmd_smoke_test()
    except ImportError:
        print("⚠️ PMD adapter module not found (Waiting for Darun).")
    except AttributeError:
        print("⚠️ PMD adapter function not implemented yet.")
    except Exception as e:
        print(f"❌ PMD Exception: {e}")

    # Step 4: Final Status
    print("\n--- 🏁 Pipeline Completion Report ---")

    if rm_success:
        print("✅ RefactoringMiner: OPERATIONAL")
        try:
            # Calculate metrics only if the tool ran successfully
            # Pass the actual commit count mined in Step 1
            refm_mets.calculate_refm_metrics(repo_total_commits)
        except Exception as e:
            print(f"⚠️ Metrics Calc Error: {e}")
    else:
        print("❌ RefactoringMiner: FAILED (or Pending)")

    if pmd_success:
        print("✅ PMD: OPERATIONAL")
    else:
        print("❌ PMD: FAILED (or Pending)")

    if rm_success and pmd_success:
        print("\n🎉 SMOKE TEST PASSED: All tools are operational.")
        sys.exit(0)
    else:
        print("\n⚠️ SMOKE TEST INCOMPLETE: Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()