# analysis/engine.py
import logging
from analysis.config import Config
from analysis.ground_repo import GroundTruthRepository
from analysis.report import ReportPresenter
from analysis.strategies.fix_rate import SmellRuleAnalyzer

# Strategy Imports
from analysis.strategies.causality import CausalityAnalyzer
from analysis.strategies.weapon_matrix import WeaponMatrixAnalyzer


def main():
    print("\n" + "=" * 60)
    print("🚀 INITIALIZING INDUSTRY-GRADE ANALYSIS ENGINE")
    print("=" * 60)

    # Configure Logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # 1. Initialize Components
    config = Config()
    repo = GroundTruthRepository(config.INPUT_PATH)
    presenter = ReportPresenter(config)

    # 2. Load Data
    try:
        df_truth = repo.load_data()
    except Exception as e:
        logging.error(f"Failed to start analysis: {e}")
        return

    # 3. Register Strategies
    # To add a new table later, just add the new class here!
    strategies = [
        CausalityAnalyzer(),
        WeaponMatrixAnalyzer(),
        SmellRuleAnalyzer()
    ]

    # 4. Execution Loop
    results = {}
    for strategy in strategies:
        print(f"\n🧠 Running Strategy: {strategy.name}...")
        result_df = strategy.analyze(df_truth)

        # Save Raw Table
        presenter.save_table(result_df, strategy.name)
        results[strategy.name] = result_df

    # 5. Generate Visuals (Now more advanced!)
    print("\n🎨 Generating Figures...")

    # Chart 1: Effectiveness
    presenter.plot_effectiveness_chart(results["table2_weapon_matrix"])

    # Chart 2: Weapon Heatmap (Using the same table 2 data)
    presenter.plot_weapon_heatmap(results["table2_weapon_matrix"])

    # Chart 3: Causality Breakdown
    presenter.plot_causality_chart(results["table4_complete_matrix"])

    print("\n" + "=" * 60)
    print(f"✅ DONE. Artifacts are in: {config.BASE_OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()