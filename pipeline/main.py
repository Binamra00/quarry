import sys
import argparse
from typing import List

from pipeline import config
from pipeline.metrics import repo_mets, refm_mets, pmd_mets
from pipeline.adapters.pmd_adapt import PMDAdapter
from pipeline.adapters.refm_adapt import RefactoringMinerAdapter
from pipeline.commands.i_command import IPipelineCommand
from pipeline.commands.tools_cmd import RunToolCommand


def main():
    """
    Main Entry Point for the Smell-Ranker Pipeline.
    Implements the Command Pattern to allow autonomous or full execution.
    """

    # --- 1. Argument Parsing (The Client) ---
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")
    parser.add_argument(
        "--stage",
        # UPDATE 1: Renamed choices here
        choices=["all", "refm", "pmd"],
        default="all",
        help="Select which pipeline stage to run (default: all)"
    )
    args = parser.parse_args()

    print("🚀 Starting Smell-Ranker Pipeline")
    print(f"📂 Configuration Loaded. Workspace: {config.WORKSPACE_ROOT}")
    print(f"🎯 Target Stage: {args.stage.upper()}")

    # --- 2. Initial Setup (Phase 0) ---
    print("\n--- Step 1: Repository Verification ---")
    repo_total_commits = 0
    try:
        repo_total_commits = repo_mets.run_metrics_report()
    except Exception as e:
        print(f"⚠️ Verification Warning: {e}")

    # --- 3. Command Configuration (The Invoker Setup) ---
    commands: List[IPipelineCommand] = []

    # Configure RefactoringMiner (History)
    # UPDATE 2: Updated logic check to "refm"
    if args.stage in ["refm", "all"]:
        rm_adapter = RefactoringMinerAdapter()
        commands.append(RunToolCommand(rm_adapter))

    # Configure PMD (Static Analysis)
    # UPDATE 3: Updated logic check to "pmd"
    if args.stage in ["pmd", "all"]:
        pmd_adapter = PMDAdapter()
        commands.append(RunToolCommand(pmd_adapter))

    # --- 4. Execution Loop (The Invoker) ---
    execution_results = {}

    for command in commands:
        tool_name = command._adapter.get_tool_name()
        success = command.execute()
        execution_results[tool_name] = success

        if not success and args.stage != "all":
            print(f"\n❌ Critical Failure in {tool_name}. Aborting.")
            sys.exit(1)

    # --- 5. Metrics Calculation (Post-Processing) ---
    print("\n--- 🏁 Pipeline Completion Report ---")

    rm_name = "RefactoringMiner (History Mining)"
    if execution_results.get(rm_name, False):
        try:
            refm_mets.calculate_refm_metrics(repo_total_commits)
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (RM): {e}")

    pmd_name = "PMD Static Analysis"
    if execution_results.get(pmd_name, False):
        try:
            pmd_mets.calculate_pmd_metrics()
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (PMD): {e}")

    # --- 6. Final Exit Code ---
    if all(execution_results.values()):
        print("\n🎉 PIPELINE SUCCESS.")
        sys.exit(0)
    else:
        print("\n⚠️ PIPELINE COMPLETED WITH ERRORS.")
        sys.exit(1)


if __name__ == "__main__":
    main()