import json
from abc import ABC, abstractmethod
from pathlib import Path
from pipeline import config


class BaseMetrics(ABC):
    """
    Template Method Pattern.
    Defines the skeleton of the metrics lifecycle: Load -> Calculate -> Save -> Report.
    """

    def __init__(self, target_repo_path: Path):
        """
        Constructor Injection.
        Args:
            target_repo_path (Path): The specific repository to analyze.
        """
        self.target_repo_path = target_repo_path

    def run_report(self):
        """The Template Method (The Algorithm Skeleton)"""
        print(f"\n--- 📊 Generating Report: {self.get_tool_name()} ---")

        # Step 1: Load inputs (Abstract or Hook)
        data = self.load_data()
        if not data:
            print("⚠️ No input data found. Skipping.")
            return

        # Step 2: Calculate specific metrics (Abstract)
        metrics = self.calculate(data)

        # Step 3: Save results (Concrete/Shared)
        self.save_metrics(metrics)

        # Step 4: Print console report (Abstract)
        self.print_report(metrics)

    @abstractmethod
    def get_tool_name(self) -> str:
        """Name of the tool/stage for logging."""
        pass

    @abstractmethod
    def load_data(self):
        """Load raw JSON data from disk."""
        pass

    @abstractmethod
    def calculate(self, data) -> dict:
        """Perform the math. Returns a dictionary of metrics."""
        pass

    @abstractmethod
    def print_report(self, metrics: dict):
        """Print the ASCII tree summary to the console."""
        pass

    def get_output_path(self) -> Path:
        """Where to save the final calculated metrics."""
        # [DECOUPLING FIX] Use the injected path, not the global config
        project_name = self.target_repo_path.name

        # Default naming convention: tools/metrics_<tool>_<project>.json
        tool_slug = self.get_tool_name().lower().replace(" ", "_")
        return config.OUTPUTS_PATH / f"metrics_{tool_slug}_{project_name}.json"

    def save_metrics(self, metrics: dict):
        """Shared logic to save the dictionary to JSON."""
        output_path = self.get_output_path()
        try:
            with open(output_path, 'w') as f:
                json.dump(metrics, f, indent=2)
            print(f"📄 Metrics saved to: {output_path.name}")
        except Exception as e:
            print(f"❌ Failed to save metrics: {e}")