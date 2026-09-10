import json
import time
from pathlib import Path
from typing import Optional

from pipeline import config
from pipeline.utils import ui_strategy
from pipeline.adapters.i_adapters import IAdapter
from pipeline.state.channel_state import ChannelStateManager
from pipeline.channels.i_sources import IChannelSource, RateLimitExhausted


class ChannelAdapter(IAdapter):
    """
    Mines one trigger channel into JSONL.

    ONE adapter serves every channel. The channels differ only in HOW they fetch -- `git log`
    versus REST pagination versus a different endpoint -- and that difference is isolated in an
    IChannelSource strategy injected here. Everything the IAdapter contract cares about is
    identical across channels: naming, output path, resumable state, reference extraction, and
    JSONL streaming. Writing five adapters would have been five copies of this file.

    WHAT THIS ADAPTER DOES NOT DO
        It performs NO transformation. A record passes from the source to disk unchanged. The
        adapter's contribution is resumable state, JSONL streaming, and progress -- not content.

        It does not detect triggers, and it does not extract references. Both are pattern
        matching over `text`, both are recomputable from the mined records at any time, and
        freezing either into the mined data would mean re-mining -- and re-spending API quota --
        to change a regex. They belong to the validation notebook, and later to a detector
        promoted from it.

        It does not resolve files either. Only the ledger knows which files a commit touched;
        the join happens downstream:

            channel record -> ref (derived from text) -> commit SHA -> ledger -> files

    OUTPUT
        outputs/channel_<platform>_<channel>_<repo>.jsonl

        Appended, never rewritten. Resumption is by record id held in the state file, so an
        interrupted run continues rather than restarting -- which matters most for API-backed
        channels, where restarting re-spends quota that cannot be recovered for an hour.
    """

    # A flush is cheap relative to a lost run, but not free: the state file rewrites its id list
    # each time. Every 500 records bounds the loss without making writes dominate.
    CHECKPOINT_EVERY = 500

    def __init__(self, target_repo_path: Path, platform: str, channel: str,
                 source: IChannelSource, batch_size: int = None):
        super().__init__(target_repo_path)
        self.platform = platform
        self.channel = channel
        self.source = source
        # A run limit, not a chunk size: stop after this many NEW records and exit cleanly, with
        # state saved. Most useful for API-backed channels, where it validates a source against a
        # few hundred real records without spending an hour of quota.
        self.batch_size = batch_size if (batch_size and batch_size > 0) else None
        self.state = ChannelStateManager(target_repo_path.name, platform, channel)

    # ------------------------------------------------------------------ IAdapter contract

    def get_tool_name(self) -> str:
        return f"Channel Miner ({self.platform}/{self.channel})"

    def get_output_path(self) -> Path:
        return (config.OUTPUTS_PATH /
                f"channel_{self.platform}_{self.channel}_{self.target_repo_path.name}.jsonl")

    def execute(self) -> bool:
        print(f"--- 📡 Starting {self.get_tool_name()} ---")
        if hasattr(self.source, "describe"):
            print(f"   🌐 {self.source.describe()}")
        print(f"   {self.state.describe()}")

        # Cheap local checks first. Verifying a source costs a request against an API channel,
        # and there is no reason to spend one on a channel that is already finished or still
        # waiting on quota.
        if self.state.is_complete:
            print(f"✅ Channel already mined: "
                  f"{len(self.state.processed_ids)} records in {self.get_output_path().name}")
            return True

        wait = self.state.rate_limit_wait()
        if wait is not None:
            print(f"⏸️  Quota does not reset for another {wait // 60}m {wait % 60}s. "
                  f"Re-run after that; progress is saved.")
            return False

        # Only now confirm the source is reachable and, for a pinned commit walk, that this
        # clone can still reproduce its universe. Failing here beats mining a different history
        # and discovering it at the join.
        if hasattr(self.source, "verify"):
            try:
                self.source.verify()
            except RuntimeError as e:
                print(e)
                return False

        self._warn_if_state_and_output_disagree()

        output_path = self.get_output_path()
        total = self.source.estimated_total() if hasattr(self.source, "estimated_total") else None
        if total:
            print(f"   📊 {total:,} records to consider")

        written = skipped = seen = 0
        interrupted = False
        hit_limit = False

        try:
            with open(output_path, "a", encoding="utf-8") as out:
                for rec in self.source.fetch(self.state):
                    seen += 1
                    rid = rec.get("record_id")
                    if rid is None:
                        continue

                    if total:
                        ui_strategy.update_progress(
                            seen, total, prefix=f"   📡 {self.platform}/{self.channel}")
                    else:
                        ui_strategy.update_count(
                            seen, prefix=f"   📡 {self.platform}/{self.channel}")

                    if self.state.is_processed(rid):
                        skipped += 1
                        continue

                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    self.state.mark_processed(rid)
                    written += 1

                    if written % self.CHECKPOINT_EVERY == 0:
                        out.flush()
                        self.state.flush()

                    if self.batch_size and written >= self.batch_size:
                        hit_limit = True
                        break

            # Only a run that consumed the whole source is complete. Stopping at a limit leaves
            # the channel resumable, so the next invocation continues rather than declaring done.
            if not hit_limit:
                self.state.mark_complete()

        except RateLimitExhausted as e:
            # Not a failure: the run stopped cleanly at a known point and can resume.
            self.state.set_rate_limited(e.reset_epoch)
            return False

        except KeyboardInterrupt:
            print("\n⚠️  Interrupt detected. Saving progress...")
            interrupted = True
            return False

        except Exception as e:
            print(f"\n❌ Channel mining failed: {e}")
            return False

        finally:
            ui_strategy.clear_line()
            self.state.flush()
            if interrupted or written:
                print(f"   💾 {len(self.state.processed_ids)} records recorded in state")

        print(f"✅ {self.get_tool_name()}: {written} new, {skipped} already had, "
              f"{len(self.state.processed_ids)} total")
        if hit_limit:
            print(f"   ⏹️  Stopped at the --batch limit of {self.batch_size}. "
                  f"Re-run to continue; progress is saved.")
        return True

    # ------------------------------------------------------------------ helpers

    def _warn_if_state_and_output_disagree(self) -> None:
        """
        A JSONL with records but an empty state means the state file was deleted while the
        output was kept. Continuing would append duplicates silently. Say so rather than
        quietly corrupting the file.
        """
        output_path = self.get_output_path()
        if self.state.processed_ids or not output_path.exists():
            return
        if output_path.stat().st_size == 0:
            return
        print(
            f"\n⚠️  {output_path.name} already holds records but no progress is recorded.\n"
            f"   The state file was probably deleted without deleting the output. Continuing\n"
            f"   would append duplicates. Delete {output_path.name} to re-mine cleanly, or\n"
            f"   restore the state file.\n"
        )