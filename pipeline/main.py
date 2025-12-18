import sys
import importlib
from pipeline import config
from pipeline.metrics import refm_mets, repo_mets, pmd_mets
from pipeline.adapters import pmd_adapt, refm_adapt

# NOTE: We import adapters inside the functions or try/except blocks
# to prevent the script from crashing if a file is missing during dev.

def main():
    """
    Main Entry Point for the Smell-Ranker Pipeline.
    Phase 2 Integration: Now running both RefactoringMiner and PMD.
    """
    print("🚀 Starting Smell-Ranker Pipeline (Phase 1 & 2)")
    print(f"📂 Configuration Loaded. Drive Path: {config.DRIVE_PATH}")

    # Step 1: Verification (Phase 0)
    print("\n--- Step 1: Repository Verification ---")
    repo_total_commits = 0
    try:
        # Capture the actual commit count to pass to refm_mets later
        repo_total_commits = repo_mets.run_metrics_report()
    except Exception as e:
        print(f"⚠️ Metrics calculation failed: {e}")

    # Step 2: RefactoringMiner (Phase 1)
    print("\n--- Step 2: RefactoringMiner (History Mining) ---")
    rm_success = False
    try:
        rm_success = refm_adapt.run_refm_smoke_test()
    except ImportError:
         print("⚠️ refm_adapt module not found.")
    except Exception as e:
        print(f"❌ RefactoringMiner Exception: {e}")

    # Step 3: PMD Static Analysis (Phase 2)
    print("\n--- Step 3: PMD Static Analysis (Candidate Generation) ---")
    pmd_success = False
    try:
        # Now fully implemented
        pmd_success = pmd_adapt.run_pmd_smoke_test()
    except ImportError:
        print("⚠️ PMD adapter module not found. Check pipeline/adapters/")
    except Exception as e:
        print(f"❌ PMD Exception: {e}")

    # Step 4: Final Status
    print("\n--- 🏁 Pipeline Completion Report ---")

    if rm_success:
        print("✅ RefactoringMiner: OPERATIONAL")
        try:
            refm_mets.calculate_refm_metrics(repo_total_commits)
        except Exception as e:
            print(f"⚠️ Metrics Calc Error: {e}")
    else:
        print("❌ RefactoringMiner: FAILED")

    if pmd_success:
        print("✅ PMD: OPERATIONAL")
        try:
            # [NEW] Calculate PMD Metrics
            pmd_mets.calculate_pmd_metrics()
        except Exception as e:
            print(f"⚠️ PMD Metrics Calc Error: {e}")
    else:
        print("❌ PMD: FAILED")

    if rm_success and pmd_success:
        print("\n🎉 FULL PIPELINE SUCCESS: History and Static Analysis complete.")
        sys.exit(0)
    else:
        print("\n⚠️ PIPELINE INCOMPLETE: Check logs.")
        sys.exit(1)


if __name__ == "__main__":
    main()