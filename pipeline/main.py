import sys
import argparse
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import allocate_tools
from pipeline.utils.repo_loader import RepositoryLoader
from pipeline.metrics.repo_mets import RepoMetrics
from pipeline.metrics.refm_mets import RefmMetrics
from pipeline.metrics.pmd_mets import PMDMetrics

from pipeline.factories.adapter_fact import ToolFactory
from pipeline.commands.i_commands import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand

# [NEW] Phase 4 Imports
from pipeline.commands.heuristic_cmd import RunHeuristicsCommand
from pipeline.heuristics.strategies_factory import HeuristicFactory
# [NEW] Import the Metadata Adapter
from pipeline.adapters.metadata_adapt import MetadataAdapter


def main():
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")

    parser.add_argument("--repo",
                        # [UX] Default ensures backward compatibility for existing scripts
                        default="toy_project",
                        help="Target Repository. Can be a local folder name OR a GitHub URL.")

    parser.add_argument("--stage",
                        choices=config.VALID_STAGES,
                        default="all",
                        help="Pipeline stage. 'all' runs RefactoringMiner + PMD + Heuristics.")

    parser.add_argument("--batch-size",
                        type=int,
                        default=50,
                        help="Number of commits to process in the PMD history batch.")

    # [NEW] Granular control over heuristics
    parser.add_argument("--heuristic",
                        choices=["all", "A", "B", "C"],
                        default="all",
                        help="Which heuristic strategy to apply. Default is 'all' (Aggregated Score).")

    args = parser.parse_args()

    print("🚀 Starting Smell-Ranker Pipeline")
    print(f"📂 Configuration Loaded. Workspace: {config.WORKSPACE_ROOT.name}")

    # --- 1. TOOLCHAIN VERIFICATION ---
    try:
        print("\n--- 🛠️ Verifying Toolchain ---")
        allocate_tools.provision()
    # Catch specific errors for cleaner setup, fallback to crash on others
    except (RuntimeError, OSError) as e:
        print(f"❌ CRITICAL: Tool provisioning failed. Cannot proceed.\n   Error: {e}")
        sys.exit(1)

    # --- 2. REPOSITORY ACQUISITION (FACADE) ---
    try:
        target_repo = RepositoryLoader.ensure_local_copy(args.repo)
    # [FIX] Distinguish between User Errors (NotFound) and System Errors (Security/Git)
    except FileNotFoundError as e:
        print(f"\n❌ REPOSITORY ERROR:\n   {e}")
        sys.exit(1)
    except (ValueError, RuntimeError) as e:
        print(f"\n❌ CRITICAL ERROR:\n   {e}")
        sys.exit(1)

    print(f"🎯 Target Repository: {target_repo.name}")
    print(f"🎯 Target Stage: {args.stage.upper()}")
    print(f"🎯 Batch Size: {args.batch_size}")

    # --- 3. Initial Setup (Phase 0) ---
    if args.stage not in ["heuristics"]:
        print("\n--- Step 1: Repository Verification ---")

        default_branch = "main"

        print(f"   🔍 Detecting default branch for '{target_repo.name}'...")
        success, output = adapter_subprocess.run_command(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=str(target_repo)
        )

        if success and output:
            try:
                detected_branch = output.strip().split('/')[-1]
                if detected_branch:
                    default_branch = detected_branch
                    print(f"   ✅ Detected Remote HEAD: {default_branch}")
            except (IndexError, AttributeError):
                pass
        else:
            s, _ = adapter_subprocess.run_command(
                ["git", "rev-parse", "--verify", "master"],
                cwd=str(target_repo)
            )
            if s:
                default_branch = "master"
                print(f"   ⚠️ Remote HEAD not found. Falling back to local '{default_branch}'.")

        print(f"   🔄 Ensuring '{target_repo.name}' is on '{default_branch}'...")
        success, _ = adapter_subprocess.run_command(
            ["git", "checkout", "-f", default_branch],
            cwd=str(target_repo)
        )
        if not success:
            print(f"   ⚠️ Warning: Could not checkout '{default_branch}'. Metrics might reflect Detached HEAD state.")

        try:
            RepoMetrics(target_repo).run_report()
        except Exception as e:
            print(f"⚠️ Verification Warning: {e}")

    # --- 4. Command Configuration ---
    commands: List[IPipelineCommand] = []

    # 👇 INSERT THIS BLOCK HERE 👇
    # [NEW] Phase 0: Metadata Mining (Git Lineage)
    # Must run first to generate the history graph for heuristics
    if args.stage in ["all", "mining", "history"]:
        adapter = MetadataAdapter(target_repo)
        commands.append(RunToolCommand(adapter))
    # 👆 END OF INSERT 👆

    # A. Standard Mining Adapters (RefMiner, PMD)
    # logic: Run these if we are NOT in isolated heuristic mode
    if args.stage not in ["heuristics"]:
        active_adapters = ToolFactory.create_adapters(args.stage, target_repo, args.batch_size)
        for adapter in active_adapters:
            commands.append(RunToolCommand(adapter))

    # B. Heuristic Analysis (Phase 4)
    # logic: Run if stage is explicitly 'heuristics' OR if stage is 'all'
    if args.stage in ["heuristics", "all"]:

        # Mapping User Flags to Factory Names
        strategy_map = {
            "A": ["Complexity"],  # Heuristic A
            "B": ["AST_Proximity"],  # Heuristic B
            "C": ["Criticality"],  # Heuristic C
            "all": ["Complexity", "AST_Proximity", "Criticality"]
        }

        selected_strategies = strategy_map.get(args.heuristic, [])

        # [SAFETY] Only run strategies that are actually implemented in the Factory
        # This allows us to run "all" safely even if A and C are not built yet.
        available_strategies = [s for s in selected_strategies if s in HeuristicFactory._REGISTRY]

        if available_strategies:
            print(f"\n--- 🧠 Phase 4: Heuristic Correlation (Strategies: {available_strategies}) ---")

            # Pass the specific list of strategies to the command
            # The command will then instantiate them via the Factory
            # Note: We need to modify RunHeuristicsCommand to accept this list,
            # or simply pass the list of names to the Engine.
            # For simplicity in this architecture, the Command usually sets up the Engine.

            # Since RunHeuristicsCommand (from previous steps) encapsulated the factory call,
            # we can pass the names to it constructor if we updated it, or let it default.
            # Assuming the simpler implementation where Command handles it:

            # We need to make sure RunHeuristicsCommand accepts 'strategies' list in init
            # Check your heuristic_cmd.py implementation.
            # If it doesn't support arg injection yet, we can default to "all available".

            # Implementation assuming Command accepts the list:
            cmd = RunHeuristicsCommand(target_repo.name, strategies=available_strategies)
            commands.append(cmd)

        else:
            if args.stage == "heuristics":
                print(f"⚠️ Warning: Heuristic '{args.heuristic}' requested but no implementation found in Registry.")

    if not commands:
        print(f"⚠️ No tools matched the stage '{args.stage}'. Exiting.")
        sys.exit(0)

    # --- 5. Execution Loop ---
    execution_results = {}
    for command in commands:
        tool_name = command.get_tool_name()
        success = command.execute()
        execution_results[tool_name] = success

        if not success and args.stage != "all":
            print(f"\n❌ Critical Failure in {tool_name}. Aborting.")
            sys.exit(1)

    # --- 6. Metrics Calculation ---
    print("\n--- 🏁 Pipeline Completion Report ---\n")

    if args.stage in ["all", "refm", "history"]:
        try:
            RefmMetrics(target_repo).run_report()
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (RefM): {e}")

    if args.stage in ["all", "pmd", "static", "pmd_history"]:
        try:
            PMDMetrics(target_repo).run_report()
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (PMD): {e}")

    if all(execution_results.values()):
        print("🎉 PIPELINE SUCCESS.")
        sys.exit(0)
    else:
        print("⚠️ PIPELINE COMPLETED WITH ERRORS.")
        sys.exit(1)


if __name__ == "__main__":
    main()