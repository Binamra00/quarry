# analysis/presenter.py (renamed locally to report.py in your upload)
import polars as pl
import seaborn as sns
import matplotlib.pyplot as plt
import os
import logging
from analysis.config import Config

logger = logging.getLogger(__name__)


class ReportPresenter:
    """Handles I/O and Advanced Visualization."""

    def __init__(self, config: Config):
        self.config = config
        os.makedirs(self.config.TABLES_DIR, exist_ok=True)
        os.makedirs(self.config.FIGURES_DIR, exist_ok=True)
        sns.set_theme(style="whitegrid", font_scale=config.FONT_SCALE)

    def save_table(self, df: pl.DataFrame, name: str):
        path = f"{self.config.TABLES_DIR}/{name}.csv"
        df.write_csv(path)
        logger.info(f"💾 Table saved: {path}")

    def plot_effectiveness_chart(self, df: pl.DataFrame):
        """Figure 1: Top 15 Refactoring Types by Success Rate."""

        # [FIX] RE-AGGREGATE DETAILED DATA TO SUMMARY LEVEL
        # Input 'df' is split by Rule. We need to sum it up by Refactoring Type.
        summary_df = (
            df.group_by("refactoring_type")
            .agg([
                pl.col("Attempts").sum(),
                pl.col("Fixed_Count").sum()
            ])
            .with_columns(
                (pl.col("Fixed_Count") / pl.col("Attempts") * 100).round(1).alias("Success_Rate")
            )
        )

        # Now filter for significant data (>30 attempts TOTAL)
        pdf = summary_df.filter(pl.col("Attempts") > 30).to_pandas()
        pdf = pdf.sort_values("Success_Rate", ascending=False).head(15)

        if pdf.empty:
            logger.warning("⚠️ Not enough data for Effectiveness Chart.")
            return

        plt.figure(figsize=(12, 8))
        chart = sns.barplot(
            data=pdf,
            y="refactoring_type",
            x="Success_Rate",
            palette="viridis",
            hue="refactoring_type",
            legend=False
        )

        for i in chart.containers:
            chart.bar_label(i, fmt='%.1f%%', padding=3)

        plt.title("Refactoring Effectiveness (Top 15 Types)")
        plt.xlabel("Success Rate (%)")
        plt.ylabel("")
        plt.xlim(0, 110)

        path = f"{self.config.FIGURES_DIR}/fig_effectiveness.png"
        plt.savefig(path, bbox_inches="tight", dpi=self.config.DPI)
        plt.close()
        logger.info(f"🎨 Effectiveness Chart generated: {path}")

    def plot_weapon_heatmap(self, df: pl.DataFrame):
        """Figure 2: Heatmap of Refactoring (Rows) vs Smell (Cols)."""
        pdf = df.to_pandas()

        # [FIX] Ensure we have data before pivoting
        if "rule_name" not in pdf.columns:
            logger.error("❌ 'rule_name' missing from Weapon Matrix. Cannot generate heatmap.")
            return

        # Filter: Take Top 10 Refactorings and Top 5 Smells to keep map readable
        top_refs = pdf.groupby("refactoring_type")["Attempts"].sum().nlargest(10).index
        top_smells = pdf.groupby("rule_name")["Attempts"].sum().nlargest(5).index

        filtered = pdf[pdf["refactoring_type"].isin(top_refs) & pdf["rule_name"].isin(top_smells)]

        # Pivot: Rows=Refactoring, Cols=Smell, Values=Success_Rate
        matrix = filtered.pivot(index="refactoring_type", columns="rule_name", values="Success_Rate")

        plt.figure(figsize=(12, 8))
        sns.heatmap(
            matrix,
            annot=True,
            fmt=".0f",
            cmap="RdYlGn",
            cbar_kws={'label': 'Success Rate (%)'},
            linewidths=.5
        )

        plt.title("The Weapon Matrix: Which Refactoring Kills Which Smell?")
        plt.xlabel("Smell Type")
        plt.ylabel("Refactoring Operation")

        path = f"{self.config.FIGURES_DIR}/fig_weapon_heatmap.png"
        plt.savefig(path, bbox_inches="tight", dpi=self.config.DPI)
        plt.close()
        logger.info(f"🎨 Weapon Heatmap generated: {path}")

    def plot_causality_chart(self, df: pl.DataFrame):
        """Figure 3: Stacked Bar of Fixes vs. Failures vs. Introductions."""
        touched = df.filter(pl.col("Touched") == 1).to_pandas()

        summary = touched.groupby("Scenario_Label")["Count"].sum().reset_index()

        plt.figure(figsize=(10, 6))

        # Filter out 'Clean' to focus on interactions
        plot_data = summary[summary["Scenario_Label"] != "Clean (Safe Refactoring)"]

        if plot_data.empty:
            logger.warning("⚠️ No Causality scenarios found to plot.")
            return

        sns.barplot(
            data=plot_data,
            x="Scenario_Label",
            y="Count",
            hue="Scenario_Label",
            palette="magma"
        )

        plt.title("The Spatial Fallacy: Outcomes of Smell Interactions")
        plt.ylabel("Number of Occurrences")
        plt.xlabel("")
        plt.xticks(rotation=15)

        path = f"{self.config.FIGURES_DIR}/fig_causality_breakdown.png"
        plt.savefig(path, bbox_inches="tight", dpi=self.config.DPI)
        plt.close()
        logger.info(f"🎨 Causality Chart generated: {path}")