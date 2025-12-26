import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict

from pipeline import config


class BatchStateManager:
    """
    Manages the state of the batch processing with Buffered Persistence and Atomic Writes.
    """

    def __init__(self, repo_name: str, tool_name: str):
        self.repo_name = repo_name
        self.tool_name = tool_name
        self.state_file = config.OUTPUTS_PATH / f"batch_status_{tool_name}_{repo_name}.json"
        self.state = self._load_state()
        # Optimization: fast lookup set for O(1) checks
        self.processed_set = set(self.state.get("processed_shas", []))

    def _load_state(self) -> Dict:
        """Loads existing state or initializes fresh."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    print(f"   🔄 Loaded Batch State from: {self.state_file.name}")
                    return data
            except json.JSONDecodeError:
                timestamp = int(time.time())
                corrupt_path = self.state_file.with_suffix(f".corrupt_{timestamp}.json")
                print(f"   ⚠️ State file corrupted. Archiving to: {corrupt_path.name}")
                try:
                    shutil.move(str(self.state_file), str(corrupt_path))
                except OSError:
                    pass

        return {
            "repo": self.repo_name,
            "tool": self.tool_name,
            "last_index": -1,
            "is_complete": False,
            "processed_shas": []
        }

    def get_next_start_index(self) -> int:
        """Returns the index of the next commit to process."""
        return self.state.get("last_index", -1) + 1

    def is_commit_processed(self, commit_hash: str) -> bool:
        """Fast O(1) lookup to check if a commit is already done."""
        return commit_hash in self.processed_set

    def save_progress(self, commit_hash: str, index: int, total: int, flush: bool = False):
        """
        Updates the in-memory state.
        """
        if commit_hash not in self.processed_set:
            self.state["processed_shas"].append(commit_hash)
            self.processed_set.add(commit_hash)

        self.state["last_index"] = index

        if index >= total - 1:
            self.state["is_complete"] = True
            flush = True

        if flush:
            self.flush()

    def flush(self):
        """
        Atomic Write Strategy.
        Writes to a temp file first, then renames it.
        """
        temp_path = self.state_file.with_suffix(".tmp")
        try:
            with open(temp_path, 'w') as f:
                json.dump(self.state, f, indent=2)

            os.replace(temp_path, self.state_file)

        except Exception as e:
            print(f"   ⚠️ Failed to save batch state: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    # Best-effort cleanup: if temp file can't be deleted, there's nothing else to do.
                    pass