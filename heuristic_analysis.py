import polars as pl
import os

# Configuration
INPUT_FILE = "workspace_data/outputs/ground_truth_commons-lang.parquet"
OUTPUT_DIR = "workspace_data/outputs/tables"


def get_overlap_col(df):
    """Helper to find the correct overlap column dynamically."""
    if "spatial_overlap" in df.columns:
        return pl.col("spatial_overlap").cast(pl.Boolean)
    elif "score_AST_Proximity" in df.columns:
        # In your strategy, 1.0 means MATCH (True), 0.0 means NO MATCH (False)
        return pl.col("score_AST_Proximity") == 1.0
    else:
        print("⚠️ Warning: No overlap column found. Defaulting to True.")
        return pl.lit(True)


def analyze_complete_matrix():
    print(f"🚀 Starting Complete Matrix Analysis...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: File {INPUT_FILE} not found.")
        return

    df = pl.read_parquet(INPUT_FILE)
    print(f"✅ Loaded {len(df):,} rows.")

    # 1. PREPARE COLUMNS (Clean Booleans -> Integers)
    # Use the helper to find the real overlap data
    df = df.with_columns(
        get_overlap_col(df).cast(pl.Int8).alias("Touched")
    )

    # Ensure Pre/Post Smell are integers
    df = df.with_columns([
        pl.col("left_smell").cast(pl.Int8).alias("Pre_Smell"),
        pl.col("right_smell").cast(pl.Int8).alias("Post_Smell")
    ])

    # 2. GROUP BY CAUSALITY (The 4 Scenarios)
    matrix = (
        df.group_by(["Touched", "Pre_Smell", "Post_Smell"])
        .agg(pl.len().alias("Count"))
        .sort(["Touched", "Pre_Smell", "Post_Smell"], descending=True)
    )

    # 3. LABELING
    def label_scenario(touched, pre, post):
        if touched == 1:
            if pre == 1 and post == 1: return "Scenario 2: Failed Fix"
            if pre == 1 and post == 0: return "Scenario 1: True Fix"
            if pre == 0 and post == 1: return "Scenario 3: Introduction"
            if pre == 0 and post == 0: return "Clean (Safe Refactoring)"
        return "Noise (Irrelevant)"

    matrix = matrix.with_columns(
        pl.struct(["Touched", "Pre_Smell", "Post_Smell"])
        .map_elements(lambda x: label_scenario(x["Touched"], x["Pre_Smell"], x["Post_Smell"]), return_dtype=pl.Utf8)
        .alias("Scenario_Label")
    )

    print("\n" + "=" * 60)
    print("📊 COMPLETE CAUSALITY MATRIX")
    print("=" * 60)
    print(matrix)

    output_path = f"{OUTPUT_DIR}/table4_complete_matrix.csv"
    matrix.write_csv(output_path)
    print(f"\n💾 Saved Cleaned Matrix to: {output_path}")


def analyze_weapon_matrix(df: pl.DataFrame):
    print("\n" + "=" * 60)
    print("⚔️ GENERATING WEAPON MATRIX (Refactoring vs. Smell Rule)")
    print("=" * 60)

    # 1. Filter for valid ATTEMPTS only (Must verify Spatial Overlap)
    # Using the helper to handle the column name issue
    attempts_df = df.filter(get_overlap_col(df))

    # 2. Define "Success" Logic
    attempts_df = attempts_df.with_columns(
        (pl.col("left_smell") & (~pl.col("right_smell"))).alias("is_success")
    )

    # 3. Group by Refactoring Type AND Rule Name
    weapon_matrix = (
        attempts_df.group_by(["refactoring_type", "rule_name"])
        .agg([
            pl.len().alias("Attempts"),
            pl.col("is_success").sum().alias("Fixed_Count")
        ])
        .with_columns(
            (pl.col("Fixed_Count") / pl.col("Attempts") * 100).round(1).alias("Success_Rate")
        )
        .sort(["Attempts", "Success_Rate"], descending=[True, True])
    )

    output_path = f"{OUTPUT_DIR}/table2_weapon_matrix.csv"
    weapon_matrix.write_csv(output_path)
    print(f"✅ Saved Weapon Matrix to: {output_path}")
    print(weapon_matrix.head(10))


if __name__ == "__main__":
    analyze_complete_matrix()

    # Reload for the second pass to ensure clean state
    df_full = pl.read_parquet(INPUT_FILE)
    analyze_weapon_matrix(df_full)