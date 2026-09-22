import json
import re
from pathlib import Path
from typing import List

from pipeline import config
from pipeline.utils import adapter_subprocess
from pipeline.utils import ui_strategy
from pipeline.scope import CommitUniverse
from pipeline.state.output_state import OutputDerivedState
from pipeline.adapters.i_adapters import IAdapter


class DiffAdapter(IAdapter):
    """
    Adapter for git diffs, shaped for downstream language-model input.

    Walks the same commit universe as the ledger and RefactoringMiner, through the same
    CommitUniverse class, so an explicit run cannot have the three miners disagree about which
    commits exist.

    Per commit it records the message and, per changed file, the added and removed lines with the
    hunk headers, context lines and +/- prefixes removed. The prefixes are not discarded: they
    become explicit <ADDED> and <REMOVED> markers, because the distinction between an insertion
    and a deletion is signal, not formatting.

    Streams JSONL like the other adapters: O(1) memory per record while writing, resumable from
    the output itself.
    """

    # Excluded from the diff body. Hunk headers carry line numbers the model cannot use, and the
    # file headers are already recorded as `file`.
    _HUNK = re.compile(r"^@@ .*? @@")
    _FILE_HEADER = ("--- ", "+++ ")

    def __init__(self, target_repo_path: Path, batch_size: int = None,
                 universe_path: str = None, context_lines: int = 0,
                 java_only: bool = False, max_files: int = None):
        super().__init__(target_repo_path)
        self.batch_size = batch_size if (batch_size and batch_size > 0) else None

        # Same class the ledger and refm use. universe_path=None -> --all; a universe file -> the
        # pinned study grid.
        self.universe = CommitUniverse(target_repo_path.name, universe_path=universe_path)

        # Context lines are requested from git and then dropped, rather than asking git for zero,
        # so the raw diff stays available in the record for anything that wants it later.
        self.context_lines = max(0, context_lines)

        # Restricting to *.java would mirror ChangeDistiller's scope, which was a tool limitation
        # rather than a design choice. Off by default; a build file or a configuration change can
        # carry intent.
        self.java_only = java_only

        # A cap on files per commit, for the rare commit that touches hundreds. None keeps all and
        # lets the consumer decide.
        self.max_files = max_files if (max_files and max_files > 0) else None

    def get_tool_name(self) -> str:
        return "Git Diff (DRS-OSS shaping)"

    def get_output_path(self) -> Path:
        project_name = self.target_repo_path.name
        return config.OUTPUTS_PATH / f"diffs_{project_name}.jsonl"

    def _get_all_commits(self) -> List[tuple[str, int]]:
        """
        The universe, ordered oldest first.

        The "*.java" pathspec matches refm exactly: only commits touching Java files. A commit
        outside that set has no refactoring to explain and nothing for a classifier to read.
        """
        cmd = ["git", "log", *self.universe.rev_list_args(),
               "--reverse", "--format=%H|%ct", "--", "*.java"]
        success, output = adapter_subprocess.run_command(
            cmd, cwd=str(self.target_repo_path), verbose=False)

        commits = []
        if success and output:
            for line in output.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) == 2:
                    commits.append((parts[0].strip(), int(parts[1].strip())))
        return commits

    # ---------------------------------------------------------------------------------------
    # Extraction
    # ---------------------------------------------------------------------------------------

    def _parents(self, sha: str) -> List[str]:
        """Parent SHAs. A commit with more than one is a merge."""
        success, out = adapter_subprocess.run_command(
            ["git", "log", "-1", "--format=%P", sha],
            cwd=str(self.target_repo_path), verbose=False, timeout=60)
        return out.strip().split() if (success and out and out.strip()) else []

    def _message(self, sha: str) -> str:
        """The commit message as git records it, subject and body."""
        success, out = adapter_subprocess.run_command(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=str(self.target_repo_path), verbose=False, timeout=60)
        return out.strip() if (success and out) else ""

    def _raw_diff(self, sha: str) -> tuple[bool, str]:
        """
        The unified diff against the first parent.

        First parent, not all parents: on a merge commit a full diff restates every change from
        the merged branch, which would attribute another commit's work to this one. `git show -m`
        would emit one diff per parent, and the mainline one is the change this commit introduced.
        """
        cmd = ["git", "show", sha,
               f"--unified={self.context_lines}",
               "--first-parent",
               "--format=",                 # message fetched separately
               "--no-color",
               "--no-renames",              # a rename shown as delete+add keeps both sides visible
               "--"]
        if self.java_only:
            cmd.append("*.java")
        return adapter_subprocess.run_command(
            cmd, cwd=str(self.target_repo_path), verbose=False, timeout=300)

    def _split_files(self, raw: str) -> List[dict]:
        """
        Split a unified diff into per-file records, keeping only changed lines.

        Returns [{file, added: [...], removed: [...], n_added, n_removed}]. The +/- prefixes are
        stripped from the text because the list a line lands in already encodes its direction.
        """
        files, current = [], None
        for line in raw.split("\n"):
            if line.startswith("diff --git "):
                if current:
                    files.append(current)
                # "diff --git a/path b/path" -- take the b-side, which is the post-change path
                parts = line.split(" b/", 1)
                path = parts[1].strip() if len(parts) == 2 else line[len("diff --git "):].strip()
                current = {"file": path, "added": [], "removed": []}
                continue
            if current is None:
                continue
            if self._HUNK.match(line) or line.startswith(self._FILE_HEADER):
                continue
            if line.startswith("+"):
                current["added"].append(line[1:])
            elif line.startswith("-"):
                current["removed"].append(line[1:])
        if current:
            files.append(current)

        for f in files:
            f["n_added"] = len(f["added"])
            f["n_removed"] = len(f["removed"])

        # Largest change first, so a downstream cap keeps the most substantial edits.
        files.sort(key=lambda f: f["n_added"] + f["n_removed"], reverse=True)
        return files

    @staticmethod
    def render_pieces(record: dict, max_pieces: int = None) -> List[str]:
        """
        A record as DRS-OSS pieces: one for the message, one per changed file.

        A list, not one string. Each piece is encoded separately downstream and the results
        pooled, so concatenating them here would destroy the structure the pooling works on.

        Static, so a notebook can import it without constructing an adapter.
        """
        pieces = [f"<COMMIT_MESSAGE>{record.get('message', '')}</COMMIT_MESSAGE>"]
        # Callers classifying intent should skip records where is_merge is true; this renders
        # whatever it is given.
        #
        # Blank lines are dropped HERE rather than at mining time. An added or removed empty line
        # is a real change and belongs in the record, but it costs a token and carries no signal
        # for a classifier -- roughly one changed line in seven on the toy project. The stored
        # data stays faithful; the rendered input does not pay for it.
        for f in record.get("files") or []:
            removed = [l for l in (f.get("removed") or []) if l.strip()]
            added = [l for l in (f.get("added") or []) if l.strip()]
            if not removed and not added:
                continue                    # whitespace-only change to this file
            part = [f"<FILE>{f.get('file')}</FILE>"]
            if removed:
                part.append("<REMOVED>" + "\n".join(removed) + "</REMOVED>")
            if added:
                part.append("<ADDED>" + "\n".join(added) + "</ADDED>")
            pieces.append("\n".join(part))
        return pieces[:max_pieces] if max_pieces else pieces

    # ---------------------------------------------------------------------------------------

    def execute(self) -> bool:
        print(f"--- ⚡ Starting {self.get_tool_name()} [Streaming Mode] ---")
        print(f"   🌐 {self.universe.describe()}")
        if self.java_only:
            print("   ⚠️  --java-only: non-Java changes will be absent from the diff bodies")
        if self.max_files:
            print(f"   ⚠️  --max-files {self.max_files}: larger commits will be capped")

        try:
            self.universe.verify_against(self.target_repo_path)
        except RuntimeError as e:
            print(e)
            return False

        all_commits = self._get_all_commits()
        if not all_commits:
            print("❌ Error: No commits found.")
            return False

        # Progress from the output, via the same class the ledger, refm and CK use.
        state = OutputDerivedState(self.get_output_path(), "sha1", label="diff")
        remaining = [(sha, ts) for sha, ts in all_commits if not state.is_processed(sha)]

        if not remaining:
            print(f"✅ Analysis already complete ({len(state)} commits).")
            return True

        if self.batch_size:
            remaining = remaining[:self.batch_size]

        print(f"   🔄 Resuming: {len(state)} already recorded. "
              f"Processing {len(remaining)} commits this run"
              f"{f' (--batch limit {self.batch_size})' if self.batch_size else ''}...")

        output_dir = self.get_output_path().parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"❌ Error: Failed to create output directory '{output_dir}': {e}")
            return False

        log_path = self.get_log_path()
        counts = {"success": 0, "empty_diff": 0, "crash": 0}
        n_merge = 0

        with open(self.get_output_path(), "a", encoding="utf-8") as stream_file, \
                open(log_path, "a", encoding="utf-8") as log_file:
            try:
                for i, (sha, ts) in enumerate(remaining):
                    ui_strategy.update_progress(
                        i + 1, len(remaining), prefix=f"   ⛏️  Diffing [{sha[:7]}]")

                    record = {
                        "repository": str(self.target_repo_path),
                        "sha1": sha,
                        "timestamp": ts,
                        "message": "",
                        "files": [],
                        "n_files": 0,
                        "n_files_total": 0,
                        "truncated": False,
                        "is_merge": False,
                        "n_parents": 0,
                        "status": "crash",
                    }

                    parents = self._parents(sha)
                    record["n_parents"] = len(parents)
                    # Flagged, not dropped. A merge is recorded because refm walks the same
                    # universe and a missing record would make the two sets disagree -- but its
                    # message is usually generated boilerplate and its first-parent diff is the
                    # whole merged branch, so a consumer classifying intent should exclude it.
                    record["is_merge"] = len(parents) > 1

                    record["message"] = self._message(sha)
                    success, raw = self._raw_diff(sha)

                    if not success:
                        # A failure is data. The record is written with status=crash so the run
                        # is visibly incomplete rather than merely short, and OutputDerivedState
                        # will not re-attempt it silently on the next run.
                        log_file.write(f"\n[FAILURE] git show failed for {sha}\n")
                        if raw:
                            log_file.write(f"[OUTPUT] {raw[:2000]}\n")
                        counts["crash"] += 1
                    else:
                        files = self._split_files(raw or "")
                        record["n_files_total"] = len(files)
                        if self.max_files and len(files) > self.max_files:
                            files = files[:self.max_files]
                            record["truncated"] = True
                        record["files"] = files
                        record["n_files"] = len(files)
                        record["status"] = "success" if files else "empty_diff"
                        counts[record["status"]] += 1
                    if record["is_merge"]:
                        n_merge += 1

                    stream_file.write(json.dumps(record, ensure_ascii=False) + "\n")

            except KeyboardInterrupt:
                print("\n⚠️  Interrupt detected! Output stream saved safely.")
                return False

        summary = " | ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"✅ Success. Streamed {sum(counts.values())} commits to "
              f"{self.get_output_path().name}")
        print(f"   {summary}")
        if n_merge:
            print(f"   ℹ️  {n_merge} merge commit(s) recorded and flagged is_merge=true. Their "
                  f"first-parent diff is the whole merged branch and their message is usually "
                  f"generated, so filter them before classifying intent.")
        if counts["crash"]:
            print(f"   ⚠️  {counts['crash']} commit(s) recorded as crash -- see "
                  f"{log_path.name}. Re-running does not retry them; their records exist.")
        if self.batch_size and sum(counts.values()) >= self.batch_size:
            print(f"   ⏹️  Stopped at the --batch limit of {self.batch_size}. "
                  f"Re-run to continue; the output records what is done.")
        return True