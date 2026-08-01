"""
Resumable miner progress.

Two strategies, and which applies depends on one question: can the miner's own output
reconstruct its progress?

    output_state    YES. A miner that writes one record per unit of work, carrying that unit's
                    id, needs no separate record of what it has done -- the output IS that
                    record. Used by ledger, RefactoringMiner and CK.

                    This removes a real failure: a state file is a second record of the same
                    fact, and a process killed between writing a record and flushing that file
                    re-does work whose output is already on disk. Flushing on interrupt narrows
                    the window; SIGKILL, OOM and power loss ignore handlers entirely.

    channel_state   NO. The channel miner's position in a paginated remote, and the moment an
                    API quota resets, exist nowhere in its records. That state must be persisted
                    separately, atomically, because losing it means re-spending quota that
                    cannot be recovered for an hour.

The asymmetry is the design, not an inconsistency: a state file is kept only where the output
cannot carry the information.
"""
from pipeline.state.output_state import OutputDerivedState
from pipeline.state.channel_state import ChannelStateManager

__all__ = ["OutputDerivedState", "ChannelStateManager"]