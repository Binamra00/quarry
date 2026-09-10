"""
Mining scope: deciding WHICH commits/snapshots a miner should look at.

CommitUniverse (Strategy) resolves the commit walk for the history miners -- FULL (--all,
matching metadata) or EXPLICIT (the pinned study grid). Sampler resolves the snapshot SHA
set for CK from a rel_hist manifest.

Called at MINING time -- CommitUniverse by the ledger/refm adapters, Sampler by CK.
"""
from pipeline.scope.commit_universe import CommitUniverse
from pipeline.scope.snapshot_sampler import Sampler

__all__ = ["CommitUniverse", "Sampler"]