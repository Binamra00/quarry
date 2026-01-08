import sys
import argparse
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import allocate_tools
from pipeline.utils.repo_loader import RepositoryLoader # [NEW] Import Loader
from pipeline.metrics.repo_mets import RepoMetrics
from pipeline.metrics.refm_mets import RefmMetrics
from pipeline.metrics.pmd_mets import PMDMetrics

from pipeline.factories.adapter_fact import ToolFactory
from pipeline.commands.i_command import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand


def main():
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")

    parser.add_argument("--repo",
                        required=True, # [UX] Made required for clarity
                        help="Target Repository. Can be a local folder name OR a GitHub URL.")

    parser.add_argument("--stage",
                        choices=config.VALID_STAGES,
                        default="all",
                        help="Pipeline stage. 'all' runs RefactoringMiner + PMD Stateful Batch.")

    parser.add_argument("--batch-size",
                        type=int,
                        default=50,
                        help="Number of commits to process in the PMD history batch.")

    args = parser.parse_args()

    print("🚀 Starting Smell-Ranker Pipeline")
    print(f"📂 Configuration Loaded. Workspace: {config.WORKSPACE_ROOT.name}")

    # --- 1. TOOLCHAIN VERIFICATION ---
    try:
        print("\n--- 🛠️ Verifying Toolchain ---")
        allocate_tools.provision()
    except Exception as e:
        print(f"❌ CRITICAL: Tool provisioning failed. Cannot proceed.\n   Error: {e}")
        sys.exit(1)

    # --- 2. REPOSITORY ACQUISITION (FACADE) ---
    # [FIX] Securely resolve URL or Local Path
    try:
        target_repo = RepositoryLoader.ensure_local_copy(args.repo)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        sys.exit(1)

    print(f"🎯 Target Repository: {target_repo.name}")
    print(f"🎯 Target Stage: {args.stage.upper()}")
    print(f"🎯 Batch Size: {args.batch_size}")

    # --- 3. Initial Setup (Phase 0) ---
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

    active_adapters = ToolFactory.create_adapters(args.stage, target_repo, args.batch_size)

    for adapter in active_adapters:
        commands.append(RunToolCommand(adapter))

    if not commands:
        print(f"⚠️ No tools matched the stage '{args.stage}'. Exiting.")
        sys.exit(0)

    # --- 5. Execution Loop ---
    execution_results = {}
    for command in commands:
        tool_name = command._adapter.get_tool_name()
        success = command.execute()
        execution_results[tool_name] = success

        if not success and args.stage != "all":
            print(f"\n❌ Critical Failure in {tool_name}. Aborting.")
            sys.exit(1)

    # --- 6. Metrics Calculation ---
    print("\n--- 🏁 Pipeline Completion Report ---")

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
        print("\n🎉 PIPELINE SUCCESS.")
        sys.exit(0)
    else:
        print("\n⚠️ PIPELINE COMPLETED WITH ERRORS.")
        sys.exit(1)


if __name__ == "__main__":
    main()