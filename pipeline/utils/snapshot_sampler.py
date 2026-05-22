import subprocess
import re
from pathlib import Path
from typing import Set
from pipeline import config


class Sampler:
    """
    Implements Release-Level (Tag-Level) Sampling for longitudinal MSR studies.

    SCIENTIFIC VALIDITY:
    Replaces commit-level sampling to avoid the "broken snapshot" problem
    (Palomba et al., 2015) and focuses solely on actualized architectural
    debt present in official releases (Peters and Zaidman, 2012).
    """

    def __init__(self, target_repo: Path, version_file: str):
        self.target_repo = target_repo
        self.repo_name = target_repo.name
        self.version_file = version_file

        # Securely route through the config singleton
        self.file_path = config.VERSIONS_PATH / self.version_file

        # Load the dynamic list
        self.target_versions = self._load_versions()

    def _load_versions(self) -> list:
        """Loads the target versions from the specified JSON file."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"❌ Error: Version file not found at {self.file_path}")

        try:
            import json
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Support either a flat list `["1.0", "2.0"]`
                # or a dictionary `{"versions": ["1.0", "2.0"]}`
                if isinstance(data, list):
                    return [str(v) for v in data]
                elif isinstance(data, dict) and "versions" in data:
                    return [str(v) for v in data["versions"]]
                else:
                    raise ValueError(f"❌ Error: {self.version_file} must contain a list of strings.")
        except json.JSONDecodeError:
            raise RuntimeError(f"❌ Error: {self.version_file} is not a valid JSON file.")

    def get_priority_shas(self) -> Set[str]:
        """
        Extracts the commit SHAs for the targeted official release tags.
        """
        print(f"\n--- 🎯 Starting Release-Level Sampling (Tag Mining) ---")
        sampled_shas = set()

        # Execute Git command to list all tags and their underlying commit SHAs
        # %(*objectname) gets the true commit for annotated tags.
        # %(objectname) gets the commit for lightweight tags.
        cmd = ["git", "for-each-ref", "--format=%(refname:short)|%(*objectname)|%(objectname)", "refs/tags"]

        try:
            result = subprocess.run(cmd, cwd=str(self.target_repo), capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split("\n")
        except Exception as e:
            print(f"   ❌ Git command failed: {e}")
            return sampled_shas

        # Build a mapping of clean version numbers to Commit SHAs
        version_to_sha = {}
        for line in lines:
            if not line.strip(): continue
            parts = line.split('|')
            tag_name = parts[0]
            commit_sha = parts[1] if parts[1] else parts[2]

            # Apache Commons Lang has used various tag formats over 20 years:
            # e.g., 'LANG_3_1', 'commons-lang-3.14.0', 'rel/commons-lang-3.14.0'
            # We extract the clean numeric version (e.g., '3.14.0') using regex.
            normalized_tag = tag_name.replace('_', '.')  # Convert LANG_3_1 to LANG.3.1
            match = re.search(r'(\d+\.\d+(?:\.\d+)?)', normalized_tag)

            if match:
                clean_version = match.group(1)
                version_to_sha[clean_version] = commit_sha

            # Also map the literal tag name just in case
            version_to_sha[tag_name] = commit_sha

        # Match our target list against the discovered Git tags
        matched_versions = []
        for v in self.target_versions:
            # Special case for 3.11 vs 3.11.0 discrepancies
            search_versions = [v, f"{v}.0", v.replace(".0", "")]

            found = False
            for sv in search_versions:
                if sv in version_to_sha:
                    sampled_shas.add(version_to_sha[sv])
                    matched_versions.append(v)
                    found = True
                    break

            if not found:
                print(f"   ⚠️ Could not find a matching git tag for version: {v}")

        print(f"   ✅ Release Sampling Complete.")
        print(f"      - Target Releases: {len(self.target_versions)}")
        print(f"      - Matched Tags:    {len(matched_versions)}")
        print(f"      - Extracted SHAs:  {len(sampled_shas)}")

        return sampled_shas