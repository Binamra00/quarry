# analysis_engine/config.py
from dataclasses import dataclass
import os


@dataclass
class Config:
    # Paths
    INPUT_PATH: str = "workspace_data/outputs/ground_truth_commons-lang.parquet"
    BASE_OUTPUT_DIR: str = "workspace_data/outputs/artifacts"

    # Sub-directories
    TABLES_DIR: str = os.path.join(BASE_OUTPUT_DIR, "tables")
    FIGURES_DIR: str = os.path.join(BASE_OUTPUT_DIR, "figures")

    # Chart Styling (Paper Ready)
    FIG_SIZE: tuple = (10, 6)
    DPI: int = 300
    FONT_SCALE: float = 1.2
    COLOR_PALETTE: str = "viridis"