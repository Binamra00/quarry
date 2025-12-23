import json
from pathlib import Path
from typing import List, Dict, Optional
from pipeline import config


class BatchStateManager:
    """
    Manages the state of the batch processing to allow the pipeline
    to resume exactly where it left off after a Colab timeout.
    """

    def __init__(self, repo_name: str, tool_name: str):
        """
        Args:
            repo_name (str): The name of the repository (e.g., 'toy_project').
            tool_name (str): The name of the tool using batching (e.g., 'pmd_history').
        """
        self.repo_name = repo_name
        self.tool_name = tool_name

        # State file location: Thesis_Project/outputs/batch_status_<tool>_<repo>.json
        self.state_file = config.OUTPUTS_PATH / f"batch_status_{tool_name}_{repo_name}.json"

        # Load existing state or initialize fresh
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Loads existing state from Drive or initializes a fresh state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    print(f"   🔄 Loaded Batch State from: {self.state_file.name}")
                    return json.load(f)
            except json.JSONDecodeError:
                print("   ⚠️ State file corrupted. Starting fresh.")

        # Default / Fresh State
        return {
            "repo": self.repo_name,
            "tool": self.tool_name,
            "processed_shas": [],  # List of completed commit hashes
            "last_index": -1,  # 0-based index of the last processed commit in the full list
            "is_complete": False
        }

    def save_progress(self, commit_hash: str, index: int, total: int):
        """
        Updates the state and writes to Drive immediately.
        Call this AFTER a commit is successfully analyzed.
        """
        self.state["processed_shas"].append(commit_hash)
        self.state["last_index"] = index

        # If we just processed the last commit in the repo, mark complete
        if index >= total - 1:
            self.state["is_complete"] = True

        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"   ⚠️ Failed to save batch state: {e}")

    def get_next_batch(self, all_commits: List[str], batch_size: int) -> List[str]:
        """
        Determines the next slice of commits to process based on previous progress.

        Args:
            all_commits: The full list of SHA-1 hashes from git rev-list.
            batch_size: How many commits to process in this run.

        Returns:
            List[str]: A sub-list of commits to process now.
        """
        if self.state["is_complete"]:
            return []

        start_index = self.state["last_index"] + 1
        end_index = start_index + batch_size

        # Slice safely (Python handles out-of-bounds slicing automatically)
        batch = all_commits[start_index:end_index]

        if not batch:
            # If batch is empty, we must be done
            self.state["is_complete"] = True
            return []

        print(f"   📊 Batch Scope: Commits {start_index + 1} to {start_index + len(batch)} (of {len(all_commits)})")
        return batch

    def is_processed(self, commit_hash: str) -> bool:
        """Fast check if a commit is already done (useful for idempotency)."""
        return commit_hash in self.state["processed_shas"]