import subprocess
import re
import json
from pathlib import Path
from typing import Set, List, Dict
from pipeline import config


class Sampler:
    """
    Release-Level (Tag-Level) Sampling for longitudinal MSR studies.

    V3 BEHAVIOR (rel_hit manifests):
      Consumes pre-resolved (tag, sha) entries produced by the universal
      release-tag miner (998 GA rule, SHA-deduped, divergence-aware grid).
      SHAs are taken directly from the manifest — no re-resolution — and
      verified to exist as commits in the target repo.

    LEGACY BEHAVIOR (V1 flat version lists):
      Falls back to regex tag resolution for old-format inputs so the
      frozen V1/SRC pipeline keeps running unchanged. NOTE: the legacy
      path's last-write-wins resolution can select RC tags over plain GA
      tags for some naming schemes (e.g. LANG_3_5_RC2 over LANG_3_5);
      it is retained for backward compatibility only. All V3 runs must
      use rel_hit manifests.
    """

    def __init__(self, target_repo: Path, version_file: str):
        self.target_repo = target_repo
        self.repo_name = target_repo.name
        self.version_file = version_file
        self.file_path = config.VERSIONS_PATH / self.version_file

        self.entries: List[Dict] = []      # rel_hit mode: [{tag, sha, commit_date, version}]
        self.target_versions: List[str] = []  # legacy mode
        self.mode = self._load()
        self.sha_to_tag: Dict[str, str] = {}

    def _load(self) -> str:
        if not self.file_path.exists():
            raise FileNotFoundError(f"❌ Version file not found: {self.file_path}")
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            raise RuntimeError(f"❌ {self.version_file} is not valid JSON.")

        # --- V3: rel_hit manifest with pre-resolved entries ---
        if isinstance(data, dict) and "entries" in data:
            self.entries = data["entries"]
            if not self.entries:
                raise ValueError(f"❌ {self.version_file}: 'entries' is empty.")
            for e in self.entries:
                if not e.get("sha") or not e.get("tag"):
                    raise ValueError(f"❌ {self.version_file}: entry missing tag/sha: {e}")
            return "rel_hit"

        # --- Legacy: flat list or {"versions": [...]} of version numbers ---
        if isinstance(data, list):
            self.target_versions = [str(v) for v in data]
            return "legacy"
        if isinstance(data, dict) and "versions" in data:
            self.target_versions = [str(v) for v in data["versions"]]
            return "legacy"
        raise ValueError(f"❌ {self.version_file}: unrecognized format.")

    # ------------------------------------------------------------------
    def get_priority_shas(self) -> Set[str]:
        print(f"\n--- 🎯 Release-Level Sampling ({self.mode} mode) ---")
        if self.mode == "rel_hit":
            return self._shas_from_manifest()
        return self._shas_from_legacy_resolution()

    def get_ordered_entries(self) -> List[Dict]:
        """Chronologically ordered (tag, sha, date) entries — rel_hit mode only."""
        if self.mode != "rel_hit":
            raise RuntimeError("Ordered entries require a rel_hit manifest.")
        return list(self.entries)

    # ------------------------------------------------------------------
    def _verify_commit(self, sha: str) -> bool:
        """True iff sha resolves to a commit object in the target repo."""
        r = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                           cwd=str(self.target_repo), capture_output=True)
        return r.returncode == 0

    def _shas_from_manifest(self) -> Set[str]:
        sampled, missing = set(), []
        for e in self.entries:
            if self._verify_commit(e["sha"]):
                sampled.add(e["sha"])
                self.sha_to_tag[e["sha"]] = e["tag"]
            else:
                missing.append(e["tag"])
        if missing:
            # Hard failure: the manifest and the clone disagree — wrong clone,
            # shallow clone, or stale manifest. Never silently skip snapshots.
            raise RuntimeError(
                f"❌ {len(missing)} manifest SHAs absent from {self.repo_name} "
                f"(e.g. {missing[:3]}). Re-clone full history or regenerate the manifest.")
        print(f"   ✅ {len(sampled)} snapshot SHAs loaded directly from manifest "
              f"({self.entries[0]['tag']} → {self.entries[-1]['tag']}); all verified in repo.")
        return sampled

    # ------------------------------------------------------------------
    def _shas_from_legacy_resolution(self) -> Set[str]:
        """V1-compatible path. Retained verbatim in behavior; see class docstring."""
        sampled_shas = set()
        cmd = ["git", "for-each-ref", "--sort=version:refname",
               "--format=%(refname:short)|%(*objectname)|%(objectname)", "refs/tags"]
        try:
            result = subprocess.run(cmd, cwd=str(self.target_repo),
                                    capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split("\n")
        except Exception as e:
            print(f"   ❌ Git command failed: {e}")
            return sampled_shas

        version_to_sha = {}
        for line in lines:
            if not line.strip(): continue
            parts = line.split('|')
            tag_name = parts[0]
            commit_sha = parts[1] if parts[1] else parts[2]
            normalized_tag = tag_name.replace('_', '.')
            match = re.search(r'(\d+\.\d+(?:\.\d+)?)', normalized_tag)
            if match:
                version_to_sha[match.group(1)] = commit_sha
            version_to_sha[tag_name] = commit_sha

        matched = []
        for v in self.target_versions:
            search_versions = list(dict.fromkeys([v, f"{v}.0", v.replace(".0", "")]))
            for sv in search_versions:
                if sv in version_to_sha:
                    sampled_shas.add(version_to_sha[sv])
                    matched.append(v)
                    break
            else:
                print(f"   ⚠️ No matching git tag for version: {v}")
        print(f"   ✅ Legacy resolution: {len(matched)}/{len(self.target_versions)} matched, "
              f"{len(sampled_shas)} SHAs.")
        return sampled_shas