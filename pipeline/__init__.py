"""
Quarry -- a release-level mining pipeline for refactoring trigger analysis.

THIS MODULE EXISTS TO FIX THE STREAMS BEFORE ANYTHING WRITES TO THEM

    Every entry path -- `quarry`, `python -m pipeline`, `python -m pipeline.main`, a notebook
    doing `from pipeline import config` -- imports this package first. That makes it the only
    place guaranteed to run before any other module prints.

    WHY THAT MATTERS ON WINDOWS. When stdout is a CONSOLE, Python writes through the wide
    character API and any Unicode is fine. When stdout is a PIPE -- output redirected to a
    file, or captured by a parent process -- Python falls back to the ANSI code page, which on
    a Western install is cp1252 and cannot encode an emoji. The first `print` carrying one
    raises UnicodeEncodeError and the process dies before argparse has even seen the arguments.

    So the tool worked when run by hand and crashed under `quarry ... > run.log`, under the
    smoke test, and under any CI that captures output. Forcing UTF-8 here removes the
    difference between the two cases.
"""

import sys


def _force_utf8_streams() -> None:
    """
    Make stdout and stderr encode UTF-8 regardless of the platform's code page.

    Best effort by design: a stream that has been replaced (pytest's capture, a notebook's
    display hook, a closed handle) may not offer reconfigure, and failing to adjust it is not a
    reason to refuse to run. The second attempt drops to lossy encoding so an exotic character
    becomes a '?' rather than an exception.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


_force_utf8_streams()