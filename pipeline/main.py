import sys
import argparse
from typing import List

from pipeline import config
# [NEW] Import class-based metrics
from pipeline.metrics.repo_mets import RepoMetrics
from pipeline.metrics.refm_mets import RefmMetrics
from pipeline.metrics.pmd_mets import PMDMetrics

from pipeline.factories.adapter_fact import ToolFactory
from pipeline.commands.i_command import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand


def main():
    # ... (Arg parsing and printing remains the same) ...
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")
    parser.add_argument("--stage", choices=["all", "history", "static", "refm", "pmd"], default="all")
    args = parser.parse_args()

    print("🚀 Starting Smell-Ranker Pipeline")
    print(f"📂 Configuration Loaded. Workspace: {config.WORKSPACE_ROOT}")
    print(f"🎯 Target Stage: {args.stage.upper()}")

    # --- 2. Initial Setup (Phase 0) ---
    print("\n--- Step 1: Repository Verification ---")
    try:
        # [PATTERN] Template Method Call
        RepoMetrics().run_report()
    except Exception as e:
        print(f"⚠️ Verification Warning: {e}")

    # --- 3. Command Configuration ---
    commands: List[IPipelineCommand] = []
    active_adapters = ToolFactory.create_adapters(args.stage)

    for adapter in active_adapters:
        commands.append(RunToolCommand(adapter))

    if not commands:
        print(f"⚠️ No tools matched the stage '{args.stage}'. Exiting.")
        sys.exit(0)

    # --- 4. Execution Loop ---
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

    # [PATTERN] Template Method Calls (Polymorphic-style)
    # We no longer pass 'repo_total_commits' manually. The classes load it themselves.

    if args.stage in ["all", "refm", "history"]:
        try:
            RefmMetrics().run_report()
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (RM): {e}")

    if args.stage in ["all", "pmd", "static"]:
        try:
            PMDMetrics().run_report()
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