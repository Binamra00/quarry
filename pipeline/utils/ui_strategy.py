import sys
import time

# --- rendering policy -------------------------------------------------------------------
#
# Callers report EVERY item they handle. This module decides whether that report is worth
# drawing. Keeping the decision here means an adapter never carries a "print every N" constant:
# adapters report progress, this module renders it.
#
# Two reasons to throttle:
#   - a fast local loop can report tens of thousands of times per second, and the writes then
#     cost more than the work being measured;
#   - when output is redirected to a file or a CI log, '\r' does not overwrite, so every report
#     becomes its own line. An 8,822-commit run produced 8,822 lines.

_MIN_INTERVAL_SECONDS = 0.1     # at most ten redraws per second
_last_draw = 0.0


def _should_draw(force: bool = False) -> bool:
    global _last_draw
    now = time.monotonic()
    if force or (now - _last_draw) >= _MIN_INTERVAL_SECONDS:
        _last_draw = now
        return True
    return False


def update_progress(current: int, total: int, prefix: str = "Processing"):
    """
    Progress against a known total. Safe to call for every item.

    Args:
        current (int): Current item number.
        total (int): Total number of items.
        prefix (str): Text to show before the counter.
    """
    # The final item always draws, so a completed run never ends on a stale count.
    if not _should_draw(force=(total and current >= total)):
        return
    sys.stdout.write(f"\r{prefix} {current}/{total}...")
    sys.stdout.flush()


def update_count(current: int, prefix: str = "Processing"):
    """
    Progress for a stream whose total is not known in advance.

    Paginated remote collections do not reveal their size until fully fetched, so a
    current/total bar cannot be drawn. Show the running count instead.

    Args:
        current (int): Number of items handled so far.
        prefix (str): Text to show before the counter.
    """
    if not _should_draw():
        return
    sys.stdout.write(f"\r{prefix} {current}...")
    sys.stdout.flush()


def clear_line():
    """
    Clears the current console line.
    Useful for removing the final progress bar state before printing a new log.
    """
    global _last_draw
    _last_draw = 0.0          # next run starts able to draw immediately
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()