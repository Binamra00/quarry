import json
from pipeline.utils import adapter_subprocess
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
            # Format: "%H %P %ct" -> "CommitHash ParentHash UnixTimestamp"
            cmd = ["git", "log", "--all", "--format=%H %P %ct"]

            # Capture output using the universal adapter
            success, output_str = adapter_subprocess.run_command(
                cmd,
                cwd=str(self.target_repo_path),
                verbose=False
            )

            if not success:
                print(f"❌ Git Error: {output_str}")
                return False

            # 2. Parse and Save to JSONL
            lines = output_str.strip().split("\n")
            count = 0

            with open(output_path, "w", encoding="utf-8") as f:
                for line in lines:
                    parts = line.split()

                    if not parts:
                        continue

                    commit_sha = parts[0]
                    # Use negative indexing to get the timestamp (it's always the last part)
                    timestamp = parts[-1] if len(parts) > 1 else None
                    # Parent is the middle part if it exists (handles 3 parts: SHA Parent Timestamp)
                    parent_sha = parts[1] if len(parts) > 2 else None

                    record = {
                        "commit_sha": commit_sha,
                        "parent_sha": parent_sha,
                        "timestamp": timestamp
                    }
                    f.write(json.dumps(record) + "\n")
                    count += 1

            print(f"✅ Lineage mined: {count} commits indexed.")
            return True

        except Exception as e:
            print(f"❌ Metadata Mining Failed: {e}")
            return False