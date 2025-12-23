import sys
import argparse
from typing import List

from pipeline import config
from pipeline.metrics.repo_mets import RepoMetrics
from pipeline.metrics.refm_mets import RefmMetrics
from pipeline.metrics.pmd_mets import PMDMetrics

from pipeline.factories.adapter_fact import ToolFactory
from pipeline.commands.i_command import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand


def main():
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")

    # Dynamic Repo Switch
    parser.add_argument("--repo",
                        default="toy_project",
                        help="Name of the folder in Thesis Project/repos/ to analyze.")

    parser.add_argument("--stage",
                        choices=["all", "history", "static", "refm", "pmd", "pmd_history"],
                        default="all",
                        help="Pipeline stage to execute. 'all' now defaults to Stateful PMD.")

    # [NEW] Batch Size Control
    parser.add_argument("--batch-size",
                        type=int,
                        default=50,
                        help="Number of commits to process in the PMD history batch.")

    args = parser.parse_args()

    # --- 1. DYNAMIC TARGET RESOLUTION ---
    target_repo = config.REPOS_PATH / args.repo

    print("🚀 Starting Smell-Ranker Pipeline")
    print(f"📂 Configuration Loaded. Workspace: {config.WORKSPACE_ROOT.name}")
    print(f"🎯 Target Repository: {target_repo.name}")
    print(f"🎯 Target Stage: {args.stage.upper()}")
    print(f"🎯 Batch Size: {args.batch_size}")

    if not target_repo.exists():
        print(f"\n❌ CRITICAL ERROR: Repository not found.")
        print(f"   Looked for: {target_repo}")
        print(f"   Please clone the project into {config.REPOS_PATH} first.")
        sys.exit(1)

    # --- 2. Initial Setup (Phase 0) ---
    print("\n--- Step 1: Repository Verification ---")
    try:
        RepoMetrics(target_repo).run_report()
    except Exception as e:
        print(f"⚠️ Verification Warning: {e}")

    # --- 3. Command Configuration ---
    commands: List[IPipelineCommand] = []

    # [UPDATE] Pass batch_size to the factory
    active_adapters = ToolFactory.create_adapters(args.stage, target_repo, args.batch_size)

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

    if args.stage in ["all", "refm", "history"]:
        try:
            RefmMetrics(target_repo).run_report()
        except Exception as e:
            # Raise to debug during development
            raise e

    if args.stage in ["all", "pmd", "static", "pmd_history"]:
        # Note: PMDMetrics expects a single aggregated file.
        # During batch processing, this file might not exist yet.
        # The class handles missing data gracefully, so we can verify if it runs.
        try:
            PMDMetrics(target_repo).run_report()
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