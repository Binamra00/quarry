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
# Add this with your other imports
from pipeline.utils.pmd_inflection_sampler import Sampler


def main():
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")

    parser.add_argument("--repo",
                        # [UX] Default ensures backward compatibility for existing scripts
                        default="toy_project",
                        help="Target Repository. Can be a local folder name OR a GitHub URL.")

    parser.add_argument("--version",
                        default=None,
                        help="Target Git Tag or Commit Hash (e.g., jena-3.1.0)")

    parser.add_argument("--stage",
                        choices=config.VALID_STAGES,
                        default="all",
                        help="Pipeline stage. 'all' runs RefactoringMiner + PMD + Heuristics.")

    # [NEW] Add the Sample Flag
    parser.add_argument("--sample",
                        action="store_true",
                        default=False,
                        help="If True, applies Systematic Stratified Activity-Sampling to the lineage.")

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
                # [FIX] If the symbolic-ref output is malformed or unexpected, ignore it and
                # fall back to the default branch detection logic below.
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

    # [NEW] Handle Sampling Logic
    sampled_shas = None
    if args.sample:
        print("🎯 Sampling Mode: ON (Systematic Stratified Activity-Sampling)")
        sampler = Sampler(target_repo)
        sampled_shas = sampler.get_priority_shas(window_size=50)

    # Phase 0: Metadata Mining (Git Lineage)
    # Required for: 'history' (visualizing lineage) AND 'heuristics' (time-travel logic)
    if args.stage in ["all", "history"]:
        commands.append(RunToolCommand(MetadataAdapter(target_repo)))

    # Phase 1-3: Standard Mining Tools (RefMiner, PMD)
    # Run these unless we are in isolated heuristic mode
    if args.stage != "heuristics":
        mining_adapters = ToolFactory.create_adapters(args.stage, target_repo, args.batch_size)

        for adapter in mining_adapters:

            # [CLEAN] Polymorphic call.
            # If the adapter supports it, it configures itself.
            # If not, it safely ignores the call.
            if sampled_shas:
                adapter.set_sampling_filter(sampled_shas)

            commands.append(RunToolCommand(adapter))

    # Phase 4: Heuristic Analysis
    if args.stage in ["heuristics", "all"]:
        # Use Public API for encapsulation
        available_strategies = set(HeuristicFactory.get_available_strategies())

        # Map User Input -> Factory Names
        strategy_map = {
            "A": ["Complexity"],
            "B": ["AST_Proximity"],
            "C": ["Criticality"],
            "all": ["Complexity", "AST_Proximity", "Criticality"]
        }

        requested = strategy_map.get(args.heuristic, [])
        valid_strategies = [s for s in requested if s in available_strategies]

        if valid_strategies:
            print(f"\n--- 🧠 Phase 4: Heuristic Correlation (Strategies: {valid_strategies}) ---")
            commands.append(RunHeuristicsCommand(target_repo.name, strategies=valid_strategies))

        elif args.stage == "heuristics":
            # Fail Fast if user explicitly asked for heuristics but none exist
            print(f"❌ Fatal: No valid strategies found for request '{args.heuristic}'.")
            sys.exit(1)

    # --- 5. Execution Loop (Circuit Breaker Pattern) ---
    execution_results = {}
    pipeline_healthy = True

    for command in commands:
        tool_name = command.get_tool_name()

        # Dependency Guard: The Heuristic Engine is a CONSUMER.
        # It must fail if the upstream pipeline is unhealthy.
        if isinstance(command, RunHeuristicsCommand):
            if not pipeline_healthy:
                print(f"\n⛔ Skipping {tool_name} due to upstream mining failures.")
                execution_results[tool_name] = False
                continue  # Skips to execute() call below

        # Execute the tool
        success = command.execute()
        execution_results[tool_name] = success

        if not success:
            print(f"⚠️ {tool_name} failed or was interrupted. Marking pipeline as UNHEALTHY.")
            pipeline_healthy = False
            # [CRITICAL]: We DO NOT exit here. We continue the loop so
            # other independent miners (like PMD) can still run and save state,
            # even though the pipeline will ultimately exit with an error status.

    # --- 6. Finalization ---
    # We exit with error if ANY tool failed, ensuring CI/CD knows this run was partial.
    if not pipeline_healthy:
        print("\n❌ Pipeline completed with errors. Ground Truth was NOT generated.")
        print("Execution Summary:", execution_results)
        sys.exit(1)

    # Only run Metrics if the pipeline was completely healthy
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

    # [FIX] Removed unreachable 'if all()' check.
    # Since we passed the 'if not pipeline_healthy' check above, success is guaranteed.
    print("\n✅ SUCCESS: Pipeline finished successfully.")


if __name__ == "__main__":
    main()
