import sys
import argparse
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import allocate_tools
from pipeline.acquisition import RepositoryLoader
from pipeline.metrics.report_mets import ReportMetrics
from pipeline.metrics.refm_mets import RefmMetrics

from pipeline.factories.adapter_fact import ToolFactory
from pipeline.commands.i_commands import IPipelineCommand
from pipeline.commands.adapter_cmd import RunToolCommand

from pipeline.adapters.metadata_adapt import MetadataAdapter
# Add this with your other imports
from pipeline.scope import Sampler


def main():
    parser = argparse.ArgumentParser(description="Smell-Ranker Pipeline Orchestrator")

    parser.add_argument("--repo",
                        metavar="",
                        # [UX] Default ensures backward compatibility for existing scripts
                        default="toy_project",
                        help="Target Repository. Can be a local folder name OR a GitHub URL.")

    parser.add_argument("--version",
                        metavar="[tag_or_sha]",
                        default=None,
                        help="Mine a SINGLE checked-out version (git tag or commit). Valid for "
                             "meta, ledger, refm, ck. Mutually exclusive with --universe and --sample.")

    parser.add_argument("--stage",
                        metavar="[meta, ledger, refm, ck, report]",
                        choices=config.VALID_STAGES,
                        required=True,
                        help="Pipeline stage to execute (required). One miner per run; there is "
                             "no 'all'. Run stages individually: meta -> ledger/refm/ck -> report.")

    parser.add_argument("--sample",
                        metavar="[rel_hist_<repo>.json]",
                        type=str,
                        default=None,
                        help="Restrict CK to the snapshots listed in this rel_hist manifest. CK is "
                             "the heaviest miner, so it runs only at the snapshots the trigger "
                             "analysis prioritizes. Valid for the 'ck' stage only.")

    parser.add_argument("--batch",
                        metavar="[N]",
                        type=int,
                        default=50,
                        help="Commits per chunk for memory safety on large repos. Valid for ledger, "
                             "refm, ck. 0 = unlimited (default: 50).")

    parser.add_argument("--universe",
                        metavar="[adapter_universe_<repo>.json]",
                        type=str,
                        default=None,
                        help="Restrict the Ledger/RefactoringMiner walk to a pinned study grid "
                             "(HEAD + dangling snapshot commits). Omit to mine the FULL repository "
                             "(--all), matching metadata. Valid for 'ledger' and 'refm' only. "
                             "Mutually exclusive with --version.")

    args = parser.parse_args()

    # --- 0. ARGUMENT VALIDATION (FLAG MATRIX) ---
    # Flags belong to the miner whose job they match. One miner per run, so each guard is a
    # simple membership test -- no routing, no "all" exceptions.
    #
    #            --version  --batch  --universe  --sample
    #   meta         ✓         ✗         ✗          ✗
    #   ledger       ✓         ✓         ✓          ✗
    #   refm         ✓         ✓         ✓          ✗
    #   ck           ✓         ✓         ✗          ✓
    #   report       ✗         ✗         ✗          ✗   (read-only)
    def _reject(flag, allowed):
        print(f"\n❌ CLI CONFLICT: '{flag}' is not valid for stage '{args.stage}'.")
        print(f"   '{flag}' is only valid for: {', '.join(allowed)}.")
        sys.exit(1)

    # G1  --universe: ledger / refm only
    if args.universe and args.stage not in ["ledger", "refm"]:
        _reject("--universe", ["ledger", "refm"])
    # G2  --sample: ck only
    if args.sample and args.stage != "ck":
        _reject("--sample", ["ck"])
    # G5  --batch: ledger / refm / ck (meta is a single --all pass; report reads)
    if args.batch != 50 and args.stage not in ["ledger", "refm", "ck"]:
        _reject("--batch", ["ledger", "refm", "ck"])
    # --version: every miner, never report
    if args.version and args.stage == "report":
        _reject("--version", ["meta", "ledger", "refm", "ck"])

    # G3  --version XOR --universe (both scope the ledger/refm walk)
    if args.version and args.universe:
        print("\n❌ CLI CONFLICT: --version and --universe are mutually exclusive.")
        print("   --version pins the walk to ONE commit; --universe walks the grid. Pick one.")
        sys.exit(1)
    # G4  --version XOR --sample (single point vs multi-snapshot CK run)
    if args.version and args.sample:
        print("\n❌ CLI CONFLICT: --version and --sample are mutually exclusive.")
        print("   --version mines ONE commit; --sample mines a set of snapshots. Pick one.")
        sys.exit(1)

    # existence pre-check for file-valued flags
    from pathlib import Path as _P
    def _find(fname):
        p = _P(fname)
        if p.parent != _P("."):
            return p if p.exists() else None
        for base in (config.GRID_PATH, config.OUTPUTS_PATH, config.VERSIONS_PATH):
            if (base / p.name).exists():
                return base / p.name
        return None
    if args.universe and _find(args.universe) is None:
        print(f"\n❌ --universe file not found: {args.universe}")
        print(f"   Looked in {config.GRID_PATH}, {config.OUTPUTS_PATH}.")
        print(f"   Omit --universe to mine the full repository (--all).")
        sys.exit(1)
    if args.sample and _find(args.sample) is None:
        print(f"\n❌ --sample file not found: {args.sample}")
        print(f"   Looked in {config.VERSIONS_PATH}.")
        sys.exit(1)


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
        target_repo = RepositoryLoader.ensure_local_copy(args.repo, args.version)
    # [FIX] Distinguish between User Errors (NotFound) and System Errors (Security/Git)
    except FileNotFoundError as e:
        print(f"\n❌ REPOSITORY ERROR:\n   {e}")
        sys.exit(1)
    except (ValueError, RuntimeError) as e:
        print(f"\n❌ CRITICAL ERROR:\n   {e}")
        sys.exit(1)

    print(f"🎯 Target Repository: {target_repo.name}")
    print(f"🎯 Target Stage: {args.stage.upper()}")
    print(f"🎯 Batch Size: {args.batch}")
    print(f"🎯 Commit Universe: {'PINNED (' + args.universe + ')' if args.universe else 'FULL (--all, matches metadata)'}")
    if args.version:
        print("\n--- 🔖 Repo Revision (Trace) ---")
        adapter_subprocess.run_command(["git", "describe", "--tags", "--always"], cwd=str(target_repo))
        adapter_subprocess.run_command(["git", "rev-parse", "--short", "HEAD"], cwd=str(target_repo))

    # --- 3. Initial Setup (Phase 0) ---
    # if args.stage not in ["heuristics"]:
    print("\n--- Step 1: Repository Verification ---")

    # Fetch AND fast-forward the local branch onto origin. The previous version here ran
    # `git fetch --all --tags` then `git checkout -f <branch>`, which looks correct and is not:
    # fetch moves refs/remotes/origin/*, never refs/heads/*, so the checkout landed on a LOCAL
    # branch that could be months behind. The objects were present but HEAD pointed into the
    # past, and every adapter walking HEAD mined a truncated history without erroring.
    default_branch = RepositoryLoader.sync_to_remote(target_repo, pinned_version=args.version)

    if args.version:
        # Force checkout the specific version/tag to ensure the workspace matches the study target
        adapter_subprocess.run_command(["git", "checkout", "-f", args.version], cwd=str(target_repo))

    # NOTE: the old Phase-0 "Repository Mining" baseline was removed here. It re-walked the
    # entire git history on every run to print a summary -- a second, redundant mine on top of
    # the metadata/ledger adapters. The universe summary is now a READ-ONLY post-mining stage
    # ("report", see below and --stage report) that reads what the adapters produced.

    # --- 4. Command Configuration ---
    commands: List[IPipelineCommand] = []

    # [NEW] Handle Sampling Logic
    sampled_shas = None
    if args.sample:
        print(f"🎯 Sampling Mode: ON (Reading target tags from {args.sample})")
        try:
            sampler = Sampler(target_repo, args.sample)
            sampled_shas = sampler.get_priority_shas()
        except Exception as e:
            print(e)
            sys.exit(1)

    # Phase 0: Metadata Mining (Git Lineage)
    # Required for: 'history' (visualizing lineage)
    if args.stage == "meta":
        commands.append(RunToolCommand(MetadataAdapter(target_repo)))

    # Universe Report (read-only). Its own stage, run after mining.
    run_report_stage = args.stage == "report"

    # Mining stage: exactly one of refm / ck / ledger.
    if args.stage in ["refm", "ck", "ledger"]:
        mining_adapters = ToolFactory.create_adapters(args.stage, target_repo, args.batch,
                                                      universe_path=args.universe)

        for adapter in mining_adapters:
            # [CLEAN] Polymorphic call.
            # If the adapter supports it, it configures itself.
            # If not, it safely ignores the call.
            if sampled_shas:
                adapter.set_sampling_filter(sampled_shas)
            commands.append(RunToolCommand(adapter))

    # Phase 4: Heuristic Analysis
    # if args.stage in ["heuristics", "all"]:
    #     # Use Public API for encapsulation
    #     available_strategies = set(HeuristicFactory.get_available_strategies())
    #
    #     # Map User Input -> Factory Names
    #     strategy_map = {
    #         "A": ["Complexity"],
    #         "B": ["AST_Proximity"],
    #         "C": ["Criticality"],
    #         "all": ["Complexity", "AST_Proximity", "Criticality"]
    #     }
    #
    #     requested = strategy_map.get(args.heuristic, [])
    #     valid_strategies = [s for s in requested if s in available_strategies]
    #
    #     if valid_strategies:
    #         print(f"\n--- 🧠 Phase 4: Heuristic Correlation (Strategies: {valid_strategies}) ---")
    #         commands.append(RunHeuristicsCommand(target_repo.name, strategies=valid_strategies))
    #
    #     elif args.stage == "heuristics":
    #         # Fail Fast if user explicitly asked for heuristics but none exist
    #         print(f"❌ Fatal: No valid strategies found for request '{args.heuristic}'.")
    #         sys.exit(1)

    # --- 5. Execution Loop (Circuit Breaker Pattern) ---
    execution_results = {}
    pipeline_healthy = True

    for command in commands:
        tool_name = command.get_tool_name()

        # Dependency Guard: The Heuristic Engine is a CONSUMER.
        # It must fail if the upstream pipeline is unhealthy.
        # if isinstance(command, RunHeuristicsCommand):
        #     if not pipeline_healthy:
        #         print(f"\n⛔ Skipping {tool_name} due to upstream mining failures.")
        #         execution_results[tool_name] = False
        #         continue  # Skips to execute() call below

        # Execute the tool
        success = command.execute()
        execution_results[tool_name] = success

        if not success:
            print(f"⚠️ {tool_name} failed or was interrupted. Marking pipeline as UNHEALTHY.")
            pipeline_healthy = False
            # [CRITICAL]: We DO NOT exit here -- an adapter may run multiple commands
            # and we let independent ones save state before the run exits with error.

    # --- 6. Finalization ---
    # We exit with error if ANY tool failed, ensuring CI/CD knows this run was partial.
    if not pipeline_healthy:
        print("\n❌ Pipeline completed with errors. Ground Truth was NOT generated.")
        print("Execution Summary:", execution_results)
        sys.exit(1)

    # Only run Metrics if the pipeline was completely healthy
    print("\n--- 🏁 Pipeline Completion Report ---\n")

    if run_report_stage:
        try:
            ReportMetrics(target_repo).run_report()
        except Exception as e:
            print(f"⚠️ Universe Report Error: {e}")

    if args.stage == "refm":
        try:
            RefmMetrics(target_repo).run_report()
        except Exception as e:
            print(f"⚠️ Metrics Calc Error (RefM): {e}")

    # [FIX] Removed unreachable 'if all()' check.
    # Since we passed the 'if not pipeline_healthy' check above, success is guaranteed.
    print("\n✅ SUCCESS: Pipeline finished successfully.")


if __name__ == "__main__":
    main()