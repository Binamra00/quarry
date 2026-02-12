import json
import statistics
from pathlib import Path
from typing import List, Set, Dict, Optional

from pipeline import config


class Sampler:
    """
    Implements Systematic Stratified Activity-Sampling (SSAS) for commit selection.

    SCIENTIFIC VALIDITY:
    1. Systematic Sampling (Time): Ensures longitudinal coverage (Benestad et al., 2009).
    2. Purposive Sampling (Entropy): Target high-churn events (Nagappan et al., 2005).

    Goal: Reduce dataset size by ~96% while retaining >80% of architectural 'inflection points'.
    """

    def __init__(self, target_repo):
        self.repo_name = target_repo.name
        # Points to the 'Universe' of commits generated in Phase 0
        self.metrics_path = config.OUTPUTS_PATH / f"repo_metrics_{self.repo_name}.json"

    def get_priority_shas(self, window_size: int = 50) -> Set[str]:
        """
        Executes the sampling algorithm.

        Args:
            window_size (int): Size of the strata (default 50 commits).
                               Smaller = Higher Resolution, Larger = Smaller Dataset.

        Returns:
            Set[str]: A set of SHA strings to be processed.
        """
        print(f"\n--- 🎯 Starting Sampling Procedure (Window: {window_size}) ---")

        # 1. Load the 'Universe' of data
        data = self._load_repo_metrics()
        if not data:
            return None

        churn_map = data.get("churn_map", {})
        # Ensure we process chronologically.
        # Ideally, use the commit list order from Phase 0 if available.
        # Fallback to map keys (usually insertion order in modern Python, but not guaranteed across all versions/platforms without care).
        # Better: Rely on 'history' list if present in repo_metrics, else keys.
        all_shas = self._get_chronological_shas(data, churn_map)

        if not all_shas:
            print("   ⚠️ No commits found to sample.")
            return None

        total_commits = len(all_shas)
        sampled_shas = set()

        print(f"   📊 Population: {total_commits} commits.")
        print(f"   📐 Strategy: Systematic Stratified (Baseline + Peak Churn)")

        # 2. Execute Stratification
        # Step through the timeline in chunks of 'window_size'
        for i in range(0, total_commits, window_size):
            window = all_shas[i: i + window_size]
            if not window: continue

            # A. Temporal Baseline (The "Heartbeat")
            # Captures the state of the system at regular intervals.
            baseline_sha = window[0]
            sampled_shas.add(baseline_sha)

            # B. Entropy Peak (The "Inflection Point")
            # Finds the most volatile commit in this window.
            # Lambda Logic: Look up churn for sha, default to 0 if missing.
            peak_sha = max(window, key=lambda sha: churn_map.get(sha, 0))

            # Optimization: Only add if it's "significantly" different?
            # For now, we take the absolute max to catch the big refactor.
            sampled_shas.add(peak_sha)

        # 3. Calculate Reduction Stats
        final_count = len(sampled_shas)
        reduction_rate = 100 - (final_count / total_commits * 100)

        print(f"   ✅ Sampling Complete.")
        print(f"      - Original:  {total_commits}")
        print(f"      - Sampled:   {final_count}")
        print(f"      - Reduction: {reduction_rate:.1f}%")

        return sampled_shas

    def _load_repo_metrics(self) -> Optional[Dict]:
        """Safe loading of the JSON data."""
        if not self.metrics_path.exists():
            print(f"   ❌ Critical: Metadata not found at {self.metrics_path}")
            print(f"      Please run '--stage history' first to generate the commit universe.")
            return None

        try:
            with open(self.metrics_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ❌ Error reading metadata: {e}")
            return None

    def _get_chronological_shas(self, data: dict, churn_map: dict) -> List[str]:
        """
        Attempts to retrieve SHAs in strict chronological order.
        Prerequisite: Phase 0 should ideally save an ordered list.
        """
        # If your Phase 0 saves an ordered "commits" list, use it.
        if "history" in data and "commits" in data["history"]:
            # This assumes 'history' -> 'commits' is a list of dicts with 'sha'
            # Adjust based on your actual repo_metrics structure.
            # Based on previous repo_mets.py, it seemed to save stats, not a full list.
            pass

        # Fallback: Use the keys from churn_map.
        # In Python 3.7+, dict insertion order is preserved.
        # If Phase 0 inserted them chronologically, we are good.
        return list(churn_map.keys())