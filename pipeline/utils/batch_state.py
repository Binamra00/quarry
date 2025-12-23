import json
import shutil
import time
from pathlib import Path
from typing import List, Dict, Optional
from pipeline import config


class BatchStateManager:
    """
    Manages the state of the batch processing with Buffered Persistence.
    """

    def __init__(self, repo_name: str, tool_name: str):
        self.repo_name = repo_name
        self.tool_name = tool_name
        self.state_file = config.OUTPUTS_PATH / f"batch_status_{tool_name}_{repo_name}.json"
        self.state = self._load_state()
        self.processed_set = set(self.state["processed_shas"])

    def _load_state(self) -> Dict:
        """Loads existing state or initializes fresh."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    print(f"   🔄 Loaded Batch State from: {self.state_file.name}")
                    return json.load(f)
            except json.JSONDecodeError:
                timestamp = int(time.time())
                corrupt_path = self.state_file.with_suffix(f".corrupt_{timestamp}.json")
                print(f"   ⚠️ State file corrupted. Archiving to: {corrupt_path.name}")
                shutil.move(str(self.state_file), str(corrupt_path))

        return {
            "repo": self.repo_name,
            "tool": self.tool_name,
            "processed_shas": [],
            "last_index": -1,
            "is_complete": False
        }

    def save_progress(self, commit_hash: str, index: int, total: int, flush: bool = True):
        """
        Updates memory state immediately. Writes to disk only if flush=True.
        """
        # 1. Update Memory (Fast)
        if commit_hash not in self.processed_set:
            self.state["processed_shas"].append(commit_hash)
            self.processed_set.add(commit_hash)

        self.state["last_index"] = index

        if index == total - 1:
            self.state["is_complete"] = True
            flush = True  # Always flush on completion

        # 2. Persist to Disk (Slow - Only if requested)
        if flush:
            self._write_to_disk()

    def _write_to_disk(self):
        """Internal method to handle the physical write."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"   ⚠️ Failed to save batch state: {e}")

    def get_next_batch(self, all_commits: List[str], batch_size: int) -> List[str]:
        if self.state["is_complete"]:
            return []

        start_index = self.state["last_index"] + 1
        end_index = start_index + batch_size
        batch = all_commits[start_index:end_index]

        if not batch:
            self.state["is_complete"] = True
            self._write_to_disk()  # Ensure completion is saved
            return []

        print(f"   📊 Batch Scope: Commits {start_index + 1} to {start_index + len(batch)} (of {len(all_commits)})")
        return batch

    def is_processed(self, commit_hash: str) -> bool:
        return commit_hash in self.processed_set