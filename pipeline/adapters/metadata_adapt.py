import json
import subprocess
from pathlib import Path
from pipeline import config
from pipeline.adapters.i_adapters import IAdapter


class MetadataAdapter(IAdapter):
    """
    Adapter for Git Lineage Mining.
    Extracts parent-child commit relationships using native Git commands.
    Output: commit_lineage_<repo>.jsonl
    """

    def get_tool_name(self) -> str:
        return "Metadata Miner (Git Lineage)"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"commit_lineage_{self.target_repo_path.name}.jsonl"

    def execute(self) -> bool:
        output_path = self.get_output_path()
        print(f"   Target: {self.target_repo_path.name}")
        print(f"   📝 Output: {output_path.name}")

        try:
            # 1. Run Git Log
            # -C runs the command inside the repo directory
            # Format: "%H %P" -> "CommitHash ParentHash"
            cmd = ["git", "-C", str(self.target_repo_path), "log", "--format=%H %P"]

            # Capture output directly
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

            if result.returncode != 0:
                print(f"❌ Git Error: {result.stderr}")
                return False

            # 2. Parse and Save to JSONL
            lines = result.stdout.strip().split("\n")
            count = 0

            with open(output_path, "w", encoding="utf-8") as f:
                for line in lines:
                    parts = line.split()
                    if not parts: continue

                    commit_sha = parts[0]
                    # Take the first parent (simplifying merge commits)
                    parent_sha = parts[1] if len(parts) > 1 else None

                    record = {
                        "commit_sha": commit_sha,
                        "parent_sha": parent_sha
                    }
                    f.write(json.dumps(record) + "\n")
                    count += 1

            print(f"✅ Lineage mined: {count} commits indexed.")
            return True

        except Exception as e:
            print(f"❌ Metadata Mining Failed: {e}")
            return False