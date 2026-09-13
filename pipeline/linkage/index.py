"""
Everything the producers read, loaded once.

WHY AN INDEX OBJECT RATHER THAN LOADING INSIDE EACH PRODUCER

    Five producers need overlapping subsets of the same six files. Loading per producer would
    read the pull request stream three times and the commit stream twice, and -- worse -- would
    let two producers disagree about what "merged" means because each built its own table.

    The index is built once, is read-only to producers, and is the single place a file's shape
    is known. A change to a mined record's fields is a change here and nowhere else.

MEMBERSHIP SETS ARE OPTIONAL, AND ABSENCE IS NOT EMPTINESS

    ledger, refm and ck memberships are flags on the edge, so linkage can be run before those
    stages have. A missing artifact yields None rather than an empty set, and the flag is
    written blank rather than 0 -- "this stage has not run" and "this commit is not in it" are
    different facts and must not print the same.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pipeline import config
from pipeline.linkage.refs import references


class LinkageInputError(RuntimeError):
    """A required input is missing or has an unexpected shape."""


def _stream(path: Path, keep: Optional[List[str]] = None) -> List[dict]:
    """
    Read a mined JSONL file. UTF-8 always: channel text is not ASCII.

    Unparseable lines are skipped rather than fatal. The miners are append-only and an
    interrupted write can leave one truncated line; refusing to link because of it would make a
    recoverable situation unrecoverable.
    """
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append({k: rec.get(k) for k in keep} if keep else rec)
    return out


class LinkIndex:
    """
    The tables every producer resolves against.

      all_commits   every commit in the clone, from the metadata stage. The link target space.
      ledger/refm/ck  membership sets, or None where that stage has not run
      PR_COMMIT     pull request number -> merge commit SHA, merged pull requests only
      ISSUE_PR      number -> {(pull request number, ref_kind)}, from pull request bodies
      NUM_COMMIT    number -> {(commit SHA, ref_kind)}, from commit messages
      number_edges  filled by the adapter between passes; see IEdgeProducer
    """

    def __init__(self, repo_name: str):
        self.repo_name = repo_name
        self.dropped_absent = 0
        self.number_edges: Dict[int, list] = {}

        out = config.OUTPUTS_PATH
        self.all_commits = self._load_universe(out / f"commit_lineage_{repo_name}.jsonl")
        self.ledger = self._optional_shas(out / f"ledger_history_{repo_name}.jsonl", "sha")
        self.refm = self._optional_shas(out / f"refactorings_{repo_name}.jsonl", "sha1")
        self.ck = self._optional_shas(out / f"ck_metrics_{repo_name}.jsonl", "sha")

        self.prs = _stream(config.channel_file("github", "prs", repo_name))
        self.issues = _stream(config.channel_file("github", "issues", repo_name),
                              ["record_id"])
        self.reviews = _stream(config.channel_file("github", "pr_reviews", repo_name),
                               ["record_id", "parent_id"])
        self.comments = _stream(config.channel_file("github", "comments", repo_name),
                                ["record_id", "parent_id"])
        self.commits = _stream(config.channel_file("git", "commits", repo_name),
                               ["record_id", "text"])

        self.issue_numbers = {i["record_id"] for i in self.issues if i.get("record_id")}
        self.pr_numbers = {p["record_id"] for p in self.prs if p.get("record_id")}

        self.PR_COMMIT = self._build_pr_commit()
        self.ISSUE_PR = self._build_issue_pr()
        self.NUM_COMMIT = self._build_num_commit()

    # ------------------------------------------------------------------ loading

    @staticmethod
    def _load_universe(path: Path) -> Set[str]:
        """
        The metadata stage's commit list -- the space links may point into.

        A HARD REQUIREMENT, AND A HARD FAILURE ON THE OLD FIELD NAME. The metadata adapter once
        wrote `commit_sha` while every other miner wrote `sha`. Accepting both would keep two
        names alive indefinitely; refusing sends the one person who hits it to re-run a stage
        that takes seconds.
        """
        if not path.exists():
            raise LinkageInputError(
                f"{path.name} not found. Linkage resolves against the full commit universe, "
                f"so the metadata stage must run first:\n"
                f"   quarry --repo <project> --stage meta")

        records = _stream(path)
        if not records:
            raise LinkageInputError(f"{path.name} is empty. Re-run --stage meta.")

        if "sha" not in records[0] and "commit_sha" in records[0]:
            raise LinkageInputError(
                f"{path.name} uses the old `commit_sha` field. The metadata adapter now writes "
                f"`sha`, matching every other miner. Re-run:\n"
                f"   quarry --repo <project> --stage meta")

        shas = {r["sha"] for r in records if r.get("sha")}
        if not shas:
            raise LinkageInputError(f"{path.name} contains no `sha` values. Re-run --stage meta.")
        return shas

    @staticmethod
    def _optional_shas(path: Path, field: str) -> Optional[Set[str]]:
        """Membership set for a stage that may not have run. None means exactly that."""
        if not path.exists():
            return None
        return {r[field] for r in _stream(path, [field]) if r.get(field)}

    # ------------------------------------------------------------------ tables

    def _build_pr_commit(self) -> Dict[int, str]:
        """
        Merged pull requests only.

        THE `merged_at` GATE IS NOT DECORATION. A pull request closed WITHOUT merging still
        carries a merge_commit_sha, pointing at a throwaway test merge that exists in no branch
        and in no clone. Without the gate every abandoned pull request contributes a link to a
        commit nobody has.
        """
        return {p["record_id"]: p["merge_commit_sha"] for p in self.prs
                if p.get("record_id") and p.get("merged_at") and p.get("merge_commit_sha")}

    def _build_issue_pr(self) -> Dict[int, Set[Tuple[int, str]]]:
        """number -> the pull requests whose body references it, with the kind of reference."""
        table: Dict[int, Set[Tuple[int, str]]] = {}
        for p in self.prs:
            pr_number = p.get("record_id")
            if not pr_number:
                continue
            for number, kind in references(p.get("text")).items():
                table.setdefault(number, set()).add((pr_number, kind))
        return table

    def _build_num_commit(self) -> Dict[int, Set[Tuple[str, str]]]:
        """
        number -> the commits whose message references it, with the kind of reference.

        Read from the mined git commit channel rather than by walking the repository: the
        channel already holds every message, and its record_id IS the commit SHA, so the
        pairing costs nothing.
        """
        table: Dict[int, Set[Tuple[str, str]]] = {}
        for c in self.commits:
            sha = c.get("record_id")
            if not sha:
                continue
            for number, kind in references(c.get("text")).items():
                table.setdefault(number, set()).add((str(sha), kind))
        return table

    # ------------------------------------------------------------------ reporting

    def membership(self, sha: str) -> Dict[str, Optional[bool]]:
        """Which downstream artifacts contain this commit. None where the stage has not run."""
        return {
            "in_ledger": None if self.ledger is None else sha in self.ledger,
            "in_refm": None if self.refm is None else sha in self.refm,
            "in_ck": None if self.ck is None else sha in self.ck,
        }

    def describe_inputs(self) -> List[str]:
        def present(n, label):
            return f"{label}: {n:,}" if n else f"{label}: none"
        return [
            present(len(self.all_commits), "commits in clone"),
            present(len(self.prs), "pull requests"),
            present(len(self.issues), "issues"),
            present(len(self.reviews), "review comments"),
            present(len(self.comments), "comments"),
            present(len(self.commits), "commit messages"),
        ]
