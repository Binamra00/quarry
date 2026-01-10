from typing import List
from pathlib import Path
from pipeline import config
from pipeline.commands.i_commands import IPipelineCommand
from pipeline.heuristics.polars_engine import HeuristicEngine
from pipeline.heuristics.strategies_factory import HeuristicFactory


class RunHeuristicsCommand(IPipelineCommand):
    """
    Encapsulates the execution of Phase 4 (Correlation).
    It acts as the bridge between the CLI (main.py) and the Engine.
    """

    def __init__(self, repo_name: str, strategies: List[str] = None):
        """
        Args:
            repo_name (str): The target repository.
            strategies (List[str]): List of strategy names to run (e.g., ["AST_Proximity"]).
                                    If None, defaults to all available.
        """
        self.repo_name = repo_name
        self.strategy_names = strategies or ["AST_Proximity"]

        # Define Input/Output Paths based on convention
        self.refm_path = config.OUTPUTS_PATH / f"refactorings_{repo_name}.jsonl"
        self.pmd_path = config.OUTPUTS_PATH / f"pmd_history_{repo_name}.jsonl"
        self.output_path = config.OUTPUTS_PATH / f"ground_truth_{repo_name}.parquet"

    def execute(self) -> bool:
        print(f"\n--- 🧠 Executing Heuristic Correlation for '{self.repo_name}' ---")
        print(f"   🎯 Strategies: {self.strategy_names}")

        # 1. Validation: Ensure inputs exist
        if not self.refm_path.exists():
            print(f"❌ Missing Input: {self.refm_path.name} (Run --stage refm first)")
            return False
        if not self.pmd_path.exists():
            print(f"❌ Missing Input: {self.pmd_path.name} (Run --stage pmd first)")
            return False

        try:
            # 2. Strategy Provisioning (Dependency Injection)
            # This converts string names ["AST_Proximity"] into actual Logic Objects
            active_strategies = HeuristicFactory.create_strategies(self.strategy_names)

            if not active_strategies:
                print("⚠️ No valid strategies to run. Aborting.")
                return False

            # 3. Execution
            engine = HeuristicEngine(active_strategies)
            result = engine.run(
                refactoring_path=self.refm_path,
                pmd_path=self.pmd_path,
                output_path=self.output_path
            )

            print(f"✅ Correlation Complete. Candidates found: {result['total_candidates']}")
            return True

        except Exception as e:
            print(f"❌ Heuristic Engine Failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_tool_name(self) -> str:
        return "HeuristicEngine"