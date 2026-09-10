import json
from pipeline.utils import adapter_subprocess
from pathlib import Path
from pipeline import config
from pipeline.adapters.i_adapters import IAdapter

class MetadataAdapter(IAdapter):
    """
    Adapter for Git Lineage Mining.
    Extracts parent-child commit relationships using native Git commands.

    Mines the FULL commit universe with `git log --all` (every branch, tag, and
    disconnected root) -- this adapter is the single source of truth against which the
    subset-walking miners (ledger, RefactoringMiner) are compared.

    Records ALL parents per commit, not just the first: a merge commit has 2+ parents,
    and dropping the extra parent(s) would erase every merge from the lineage graph.
    Output field is `parent_shas` (a list): [] for a root, [p] for a normal commit,
    [p1, p2, ...] for a merge.
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
            # Format: "%H | %P | %ct" -> "CommitHash | space-separated ParentHashes | UnixTimestamp"
            # %P expands to ALL parents (empty for a root, two+ for a merge). Delimiting with
            # '|' makes the parent COUNT irrelevant to parsing -- the parents are simply the
            # middle field, however many there are.
            cmd = ["git", "log", "--all", "--format=%H|%P|%ct"]

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
            merge_count = 0
            root_count = 0

            with open(output_path, "w", encoding="utf-8") as f:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Exactly three fields by construction: SHA | parents | timestamp.
                    # A commit SHA and timestamp never contain '|', and %P is space-separated,
                    # so a well-formed line splits into exactly 3 parts. Anything else is
                    # malformed and skipped rather than mis-parsed.
                    fields = line.split("|")
                    if len(fields) != 3:
                        # Malformed line: record what we can rather than crash the whole run.
                        print(f"   ⚠️  Skipping malformed lineage line: {line[:60]}")
                        continue

                    commit_sha = fields[0].strip()
                    parent_shas = fields[1].split()   # [] root, [p] normal, [p1, p2, ...] merge
                    timestamp = fields[2].strip() or None

                    if len(parent_shas) == 0:
                        root_count += 1
                    elif len(parent_shas) >= 2:
                        merge_count += 1

                    record = {
                        "commit_sha": commit_sha,
                        "parent_shas": parent_shas,   # LIST -- all parents, not just the first
                        "timestamp": timestamp,
                    }
                    f.write(json.dumps(record) + "\n")
                    count += 1

            print(f"✅ Lineage mined: {count} commits indexed "
                  f"({merge_count} merges, {root_count} roots).")
            return True

        except Exception as e:
            print(f"❌ Metadata Mining Failed: {e}")
            return False