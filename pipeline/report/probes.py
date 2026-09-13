"""
The probes: one per kind of mined artifact.

WHICH ARTIFACTS EXIST IS DERIVED, NOT LISTED TWICE

    Channel probes are built from config.CHANNEL_PLATFORMS, the same table the miner expands
    `--channel all` from. A channel added there appears in the report automatically, including
    as a 'not mined yet' row -- which is the more useful half of a coverage report.

    CK is globbed rather than named, because a sampled run writes to a different file than a
    full one. Globbing reports whatever is actually on disk instead of asserting what should be.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from pipeline import config
from pipeline.metrics.i_reports import ArtifactCoverage, IArtifactProbe

# Statuses that mean the unit was measured. Anything else describes a failed RUN and will be
# re-attempted, so it is counted as outstanding work rather than as coverage.
TERMINAL_OK = frozenset({"success"})
TERMINAL_EMPTY = frozenset({"empty_output", "empty_methods"})


class JsonlProbe(IArtifactProbe):
    """
    Counts a JSONL stream, and tallies its statuses when it has any.

    DEDUPLICATION IS NOT OPTIONAL WHERE UNITS CAN BE RETRIED

        A miner that re-attempts failed units appends a second record for the same unit, and
        the LAST record is the current one. Counting lines therefore over-reports the moment
        any retry has happened. Passing id_field makes the probe count distinct units and read
        the final verdict for each; leaving it None means the stream has no retry semantics and
        a line is a unit.

    MALFORMED LINES ARE COUNTED, NOT HIDDEN

        A line that will not parse is still a line the miner wrote. It is reported in the note
        rather than silently dropped, because a report whose totals quietly disagree with
        `wc -l` is worse than one that explains the difference.
    """

    def __init__(self, stage: str, path: Path, id_field: Optional[str] = None):
        self.stage = stage
        self.path = Path(path)
        self.id_field = id_field

    def inspect(self) -> ArtifactCoverage:
        cov = ArtifactCoverage(stage=self.stage, artifact=self.path.name,
                               present=self.path.exists())
        if not cov.present:
            cov.note = "not mined yet"
            return cov

        latest: Dict[str, Optional[str]] = {}
        anonymous = 0          # records with no id, when an id was expected
        malformed = 0
        has_status = False

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    cov.records += 1
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
                        continue

                    status = rec.get("status")
                    if status is not None:
                        has_status = True

                    if self.id_field:
                        uid = rec.get(self.id_field)
                        if uid is None:
                            anonymous += 1
                        else:
                            # Last write wins: the newest attempt is the unit's current state.
                            latest[str(uid)] = status
                    else:
                        latest[str(cov.records)] = status
        except OSError as e:
            cov.note = f"unreadable: {e}"
            return cov

        cov.units = len(latest) + anonymous
        cov.malformed = malformed

        if has_status:
            for status in latest.values():
                key = status or "unlabelled"
                cov.status_counts[key] = cov.status_counts.get(key, 0) + 1
            cov.ok = sum(n for s, n in cov.status_counts.items() if s in TERMINAL_OK)
            cov.empty = sum(n for s, n in cov.status_counts.items() if s in TERMINAL_EMPTY)
            cov.failed = cov.units - cov.ok - cov.empty

        notes = []
        if cov.duplicates:
            notes.append(f"{cov.duplicates} retried")
        if cov.malformed:
            notes.append(f"{cov.malformed} unparseable")
        if anonymous:
            notes.append(f"{anonymous} without {self.id_field}")
        cov.note = ", ".join(notes)
        return cov


class ChannelProbe(IArtifactProbe):
    """
    A channel's records, plus whether its collection was ever finished.

    THE RECORD COUNT ALONE CANNOT SAY THIS. A channel stops early for reasons that leave a
    perfectly valid file behind: an exhausted API quota, a batch limit, an interrupted run. The
    sidecar state file is the only place that distinguishes 'the remote had 4,000 items' from
    'we have read 4,000 items so far', and a coverage report that cannot tell those apart is
    not reporting coverage.
    """

    def __init__(self, platform: str, channel: str, repo_name: str):
        self.platform = platform
        self.channel = channel
        self.repo_name = repo_name
        self.records_path = config.channel_file(platform, channel, repo_name)
        self.state_path = (config.OUTPUTS_PATH /
                           f"channel_status_{platform}_{channel}_{repo_name}.json")

    def inspect(self) -> ArtifactCoverage:
        inner = JsonlProbe(f"channel:{self.platform}/{self.channel}",
                           self.records_path).inspect()
        notes = [inner.note] if inner.note else []

        state = self._read_state()
        if state is None:
            if inner.present:
                notes.append("no state file")
        elif state.get("is_complete"):
            notes.append("complete")
        else:
            notes.append("INCOMPLETE — re-run to continue")
            page = state.get("last_page_done") or 0
            if page:
                notes.append(f"through page {page}")
            if state.get("window_since"):
                notes.append(f"window from {str(state['window_since'])[:10]}")
            if state.get("rate_limit_reset"):
                notes.append("paused on API quota")

        inner.note = "; ".join(n for n in notes if n)
        return inner

    def _read_state(self) -> Optional[dict]:
        if not self.state_path.exists():
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None


def probes_for(repo_name: str) -> List[IArtifactProbe]:
    """
    Every artifact the report should account for, in pipeline order.

    Stages appear whether or not they have been run: a missing file is a coverage fact, and
    omitting the row would make an unmined stage indistinguishable from one that does not
    exist.
    """
    out = config.OUTPUTS_PATH
    probes: List[IArtifactProbe] = [
        JsonlProbe("meta", out / f"commit_lineage_{repo_name}.jsonl"),
        JsonlProbe("ledger", out / f"ledger_history_{repo_name}.jsonl"),
        JsonlProbe("refm", out / f"refactorings_{repo_name}.jsonl"),
    ]

    # CK writes to a different file under sampling, so report what exists rather than what is
    # expected. `sha` is passed because CK is the one miner that re-attempts failed units.
    ck_files = sorted(out.glob(f"ck_metrics*{repo_name}.jsonl"))
    if ck_files:
        probes += [JsonlProbe("ck", p, id_field="sha") for p in ck_files]
    else:
        probes.append(JsonlProbe("ck", out / f"ck_metrics_{repo_name}.jsonl", id_field="sha"))

    for platform, channels in config.CHANNEL_PLATFORMS.items():
        for channel in channels:
            probes.append(ChannelProbe(platform, channel, repo_name))

    return probes
