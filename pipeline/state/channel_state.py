import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Set

from pipeline import config


class ChannelStateManager:
    """
    Resumable state for channel mining, keyed by (repo, platform, channel).

    WHY THIS IS NOT OutputDerivedState
        The other miners reconstruct progress from their own output: one record per unit of work
        means the output IS the record of what was done, and no second file can disagree with it.

        A channel miner resumes over a PAGINATED REMOTE collection whose size is unknown until
        it has been fetched, and whose retrieval can be interrupted by an API quota rather than
        by the user. It therefore tracks three things BatchState has no concept of:

            - how far pagination got, so a resumed run does not refetch from page 1
            - when the API quota resets, so a run can stop cleanly and resume later
            - whether the collection was ever seen to its end

        The idempotency idea is identical -- store processed record identifiers and skip them --
        only the identifier is an issue number or comment id rather than a commit SHA.

    WHY PAGINATION BY PAGE NUMBER IS SAFE HERE
        Only when the remote is sorted ASCENDING BY CREATION. New items then append at the END
        of the collection, so pages already processed keep their contents. Sorting by update
        time would reorder items whenever anything is edited between sessions, and a resumed run
        would silently skip or duplicate records. The miner is responsible for requesting that
        ordering; this class assumes it.

        Processed ids are still recorded, so even if a page does shift, nothing is written twice.

    STATE FILE
        outputs/channel_status_<platform>_<channel>_<repo>.json

        Written atomically (temp file + os.replace), so an interrupted write cannot corrupt
        progress that has already been earned.
    """

    def __init__(self, repo_name: str, platform: str, channel: str):
        self.repo_name = repo_name
        self.platform = platform
        self.channel = channel
        self.state_file = (config.OUTPUTS_PATH /
                           f"channel_status_{platform}_{channel}_{repo_name}.json")
        self.state = self._load_state()
        # fast membership test; the JSON list is the durable form
        self.processed_ids: Set[str] = set(self.state.get("processed_ids", []))

    # ------------------------------------------------------------------ loading

    def _load_state(self) -> Dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"   🔄 Resuming channel state: {self.state_file.name}")
                return data
            except json.JSONDecodeError:
                # Archive rather than discard: a corrupt state file may still be readable by
                # hand, and silently starting from zero would re-spend API quota.
                stamp = int(time.time())
                corrupt = self.state_file.with_suffix(f".corrupt_{stamp}.json")
                print(f"   ⚠️  State file corrupted. Archiving to {corrupt.name}")
                try:
                    shutil.move(str(self.state_file), str(corrupt))
                except OSError:
                    pass

        return {
            "repo": self.repo_name,
            "platform": self.platform,
            "channel": self.channel,
            "processed_ids": [],
            "last_page_done": 0,       # 0 = nothing fetched yet; pages are 1-indexed
            "next_url": None,          # exact resume point, cursor included (see next_page)
            "window_since": None,      # ISO 8601; set when a walk is continued past a cap
            "is_complete": False,
            "rate_limit_reset": None,  # epoch seconds; set when quota is exhausted
            "records_written": 0,
        }

    # ------------------------------------------------------------------ idempotency

    def is_processed(self, record_id) -> bool:
        return str(record_id) in self.processed_ids

    def mark_processed(self, record_id, flush: bool = False) -> None:
        rid = str(record_id)
        if rid not in self.processed_ids:
            self.processed_ids.add(rid)
            self.state.setdefault("processed_ids", []).append(rid)
            self.state["records_written"] = self.state.get("records_written", 0) + 1
        if flush:
            self.flush()

    # ------------------------------------------------------------------ pagination

    def next_page(self) -> int:
        """The page to request next. 1 on a fresh run."""
        return int(self.state.get("last_page_done", 0)) + 1

    def next_url(self) -> Optional[str]:
        """
        The exact URL to resume from, or None to start from next_page().

        Preferred over a page number wherever it exists, because it carries the platform's own
        cursor. Some endpoints cap offset pagination -- GitHub's /issues refuses anything past
        the 10,000th item -- so beyond that depth a page number cannot express where to resume
        and only the cursor can.
        """
        return self.state.get("next_url")

    def mark_page_done(self, page: int, next_url: Optional[str] = None,
                       flush: bool = True) -> None:
        """
        Record a page as fully processed, along with where to continue.

        Flushed by default: a page is a meaningful unit of work, and losing one to an unflushed
        crash costs an API request that need not be spent twice.
        """
        self.state["last_page_done"] = max(int(self.state.get("last_page_done", 0)), int(page))
        self.state["next_url"] = next_url
        if flush:
            self.flush()

    def window_since(self) -> Optional[str]:
        """
        The `since` value the current walk is filtered by, or None for the first window.

        Some endpoints stop paginating well before the collection ends -- GitHub's
        /issues/comments simply stops offering rel="next" at 30,000 items. Continuing past that
        means restarting the walk filtered to records newer than the newest one already seen.
        This records which window is in progress so a resumed run does not start from the
        beginning of time.
        """
        return self.state.get("window_since")

    def advance_window(self, since: str) -> None:
        """
        Begin a new time window. Page position resets, because the new walk is a new query.
        """
        self.state["window_since"] = since
        self.state["last_page_done"] = 0
        self.state["next_url"] = None
        self.flush()

    def mark_complete(self) -> None:
        """The remote collection was paginated to its end."""
        self.state["is_complete"] = True
        self.state["rate_limit_reset"] = None
        self.state["next_url"] = None
        self.state["window_since"] = None
        self.flush()

    @property
    def is_complete(self) -> bool:
        return bool(self.state.get("is_complete", False))

    # ------------------------------------------------------------------ rate limiting

    def set_rate_limited(self, reset_epoch: int) -> None:
        """
        Called when the API quota is spent. Records when it returns so the next invocation can
        report the wait instead of failing with an opaque error.
        """
        self.state["rate_limit_reset"] = int(reset_epoch)
        self.flush()
        wait = max(0, int(reset_epoch) - int(time.time()))
        print(f"\n   ⏸️  API quota exhausted for {self.platform}/{self.channel}. "
              f"Resets in {wait // 60}m {wait % 60}s "
              f"({time.strftime('%Y-%m-%d %H:%M', time.localtime(reset_epoch))}).")
        print(f"   Progress saved: {len(self.processed_ids)} records, "
              f"through page {self.state.get('last_page_done', 0)}. Re-run to continue.")

    def rate_limit_wait(self) -> Optional[int]:
        """
        Seconds still to wait before the quota returns, or None if it has reset (or was never
        exhausted). Clears the marker once it has expired.
        """
        reset = self.state.get("rate_limit_reset")
        if reset is None:
            return None
        remaining = int(reset) - int(time.time())
        if remaining <= 0:
            self.state["rate_limit_reset"] = None
            self.flush()
            return None
        return remaining

    def clear_rate_limit(self) -> None:
        if self.state.get("rate_limit_reset") is not None:
            self.state["rate_limit_reset"] = None
            self.flush()

    # ------------------------------------------------------------------ persistence

    # Windows denies a rename while ANY process holds the destination open -- an antivirus
    # scanner or search indexer opening the file microseconds after it is written is enough.
    # The lock is transient, so a short retry succeeds where a single attempt fails.
    RENAME_ATTEMPTS = 5
    RENAME_BACKOFF = 0.15

    def flush(self) -> bool:
        """
        Atomic write: build a temp file, then rename over the target. A crash before the rename
        leaves the previous state intact; a crash after leaves the new one. There is no window
        in which the file is half written.

        On Windows the rename can fail with PermissionError (WinError 5) even though nothing is
        wrong with the data: os.replace is atomic on POSIX, but Windows refuses it while another
        process has the destination file open, and background scanners routinely do. Retrying
        briefly clears it. Failing here does not lose mined records -- those are already in the
        JSONL -- but it does lose the record of how far pagination got, which costs API quota on
        the next run.
        """
        temp_path = self.state_file.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"   ⚠️  Could not write channel state: {e}")
            self._remove_temp(temp_path)
            return False

        last_err = None
        for attempt in range(self.RENAME_ATTEMPTS):
            try:
                os.replace(temp_path, self.state_file)
                return True
            except PermissionError as e:          # Windows: destination held open elsewhere
                last_err = e
                time.sleep(self.RENAME_BACKOFF * (attempt + 1))
            except OSError as e:
                last_err = e
                break

        print(f"   ⚠️  Could not save channel state after {self.RENAME_ATTEMPTS} attempts: "
              f"{last_err}")
        print(f"      Mined records are safe in the JSONL; only pagination progress was lost, "
              f"which costs quota on the next run.")
        self._remove_temp(temp_path)
        return False

    @staticmethod
    def _remove_temp(temp_path: Path) -> None:
        """Best-effort cleanup. A leftover .tmp is harmless; failing to remove it is not fatal."""
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ reporting

    def describe(self) -> str:
        if self.is_complete:
            return (f"{self.platform}/{self.channel} complete: "
                    f"{len(self.processed_ids)} records")
        wait = self.rate_limit_wait()
        if wait:
            return (f"{self.platform}/{self.channel} paused on quota, "
                    f"{wait // 60}m remaining; {len(self.processed_ids)} records so far")
        page = self.state.get("last_page_done", 0)
        n = len(self.processed_ids)
        if page:
            via = "cursor" if self.state.get("next_url") else f"page {page + 1}"
            win = self.state.get("window_since")
            window = f" (window from {win[:10]})" if win else ""
            return (f"{self.platform}/{self.channel} resuming from {via}{window}; "
                    f"{n} records so far")
        if n:
            # A source that does not paginate leaves last_page_done at 0, so records already
            # held are the only evidence a previous run happened. Reporting "starting fresh"
            # here would be false.
            return f"{self.platform}/{self.channel} resuming; {n} records so far"
        return f"{self.platform}/{self.channel} starting fresh"