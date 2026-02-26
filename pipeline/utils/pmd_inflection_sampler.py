# import json
# import statistics
# from pathlib import Path
# from typing import List, Set, Dict, Optional
#
# from pipeline import config
#
#
# class Sampler:
#     """
#     Implements Systematic Stratified Activity-Sampling (SSAS) for commit selection.
#
#     SCIENTIFIC VALIDITY:
#     1. Systematic Sampling (Time): Ensures longitudinal coverage (Benestad et al., 2009).
#     2. Purposive Sampling (Entropy): Target high-churn events (Nagappan et al., 2005).
#
#     Goal: Reduce dataset size by ~96% while retaining >80% of architectural 'inflection points'.
#     """
#
#     def __init__(self, target_repo):
#         self.repo_name = target_repo.name
#         # Points to the 'Universe' of commits generated in Phase 0
#         self.metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{self.repo_name}.json"
#
#     def get_priority_shas(self, window_size: int = 50) -> Set[str]:
#         """
#         Executes the sampling algorithm.
#
#         Args:
#             window_size (int): Size of the strata (default 50 commits).
#                                Smaller = Higher Resolution, Larger = Smaller Dataset.
#
#         Returns:
#             Set[str]: A set of SHA strings to be processed.
#         """
#         print(f"\n--- 🎯 Starting Sampling Procedure (Window: {window_size}) ---")
#
#         # 1. Load the 'Universe' of data
#         data = self._load_repo_metrics()
#         if not data:
#             return None
#
#         churn_map = data.get("churn_map", {})
#         # Ensure we process chronologically.
#         # Ideally, use the commit list order from Phase 0 if available.
#         # Fallback to map keys (usually insertion order in modern Python, but not guaranteed across all versions/platforms without care).
#         # Better: Rely on 'history' list if present in repo_metrics, else keys.
#         all_shas = self._get_chronological_shas(data, churn_map)
#
#         if not all_shas:
#             print("   ⚠️ No commits found to sample.")
#             return None
#
#         total_commits = len(all_shas)
#         sampled_shas = set()
#
#         print(f"   📊 Population: {total_commits} commits.")
#         print(f"   📐 Strategy: Systematic Stratified (Baseline + Peak Churn)")
#
#         # 2. Execute Stratification
#         # Step through the timeline in chunks of 'window_size'
#         for i in range(0, total_commits, window_size):
#             window = all_shas[i: i + window_size]
#             if not window: continue
#
#             # A. Temporal Baseline (The "Heartbeat")
#             # Captures the state of the system at regular intervals.
#             baseline_sha = window[0]
#             sampled_shas.add(baseline_sha)
#
#             # B. Entropy Peak (The "Inflection Point")
#             # Finds the most volatile commit in this window.
#             # Lambda Logic: Look up churn for sha, default to 0 if missing.
#             peak_sha = max(window, key=lambda sha: churn_map.get(sha, 0))
#
#             # Optimization: Only add if it's "significantly" different?
#             # For now, we take the absolute max to catch the big refactor.
#             sampled_shas.add(peak_sha)
#
#         # 3. Calculate Reduction Stats
#         final_count = len(sampled_shas)
#         reduction_rate = 100 - (final_count / total_commits * 100)
#
#         print(f"   ✅ Sampling Complete.")
#         print(f"      - Original:  {total_commits}")
#         print(f"      - Sampled:   {final_count}")
#         print(f"      - Reduction: {reduction_rate:.1f}%")
#
#         return sampled_shas
#
#     def _load_repo_metrics(self) -> Optional[Dict]:
#         """Safe loading of the JSON data."""
#         if not self.metrics_path.exists():
#             print(f"   ❌ Critical: Metadata not found at {self.metrics_path}")
#             print(f"      Please run '--stage history' first to generate the commit universe.")
#             return None
#
#         try:
#             with open(self.metrics_path, 'r') as f:
#                 return json.load(f)
#         except Exception as e:
#             print(f"   ❌ Error reading metadata: {e}")
#             return None
#
#     def _get_chronological_shas(self, data: dict, churn_map: dict) -> List[str]:
#         """
#         Attempts to retrieve SHAs in strict chronological order.
#         Prerequisite: Phase 0 should ideally save an ordered list.
#         """
#         # If your Phase 0 saves an ordered "commits" list, use it.
#         if "history" in data and "commits" in data["history"]:
#             # This assumes 'history' -> 'commits' is a list of dicts with 'sha'
#             # Adjust based on your actual repo_metrics structure.
#             # Based on previous repo_mets.py, it seemed to save stats, not a full list.
#             pass
#
#         # Fallback: Use the keys from churn_map.
#         # In Python 3.7+, dict insertion order is preserved.
#         # If Phase 0 inserted them chronologically, we are good.
#         return list(churn_map.keys())


import subprocess
import re
from pathlib import Path
from typing import Set


class Sampler:
    """
    Implements Release-Level (Tag-Level) Sampling for longitudinal MSR studies.

    SCIENTIFIC VALIDITY:
    Replaces commit-level sampling to avoid the "broken snapshot" problem
    (Palomba et al., 2015) and focuses solely on actualized architectural
    debt present in official releases (Peters and Zaidman, 2012).
    """

    def __init__(self, target_repo: Path):
        self.target_repo = target_repo
        self.repo_name = target_repo.name

        # The exact official release versions approved for the EASE 2026 study
        self.target_versions = [
            "3.20.0", "3.19.0", "3.18.0", "3.17.0", "3.16.0", "3.15.0", "3.14.0",
            "3.13.0", "3.12.0", "3.11", "3.10", "3.9", "3.8.1", "3.8", "3.7",
            "3.6", "3.5", "3.4", "3.3.2", "3.3.1", "3.3", "3.2.1", "3.2",
            "3.1", "3.0.1", "3.0", "2.6", "2.5", "2.4", "2.3", "2.2", "2.1",
            "2.0", "1.0.1", "1.0"
        ]

    def get_priority_shas(self, window_size: int = None) -> Set[str]:
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