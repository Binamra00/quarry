import csv
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from pipeline import config
from pipeline.adapters.i_adapters import IAdapter
from pipeline.linkage.i_producers import LinkEdge, REF_RANK
from pipeline.linkage.index import LinkageInputError, LinkIndex
from pipeline.linkage.producers import all_producers

LINK_COLUMNS = ("source_channel", "source_id", "resolved_via", "target_sha",
                "route", "ref_kind", "exact", "in_ledger", "in_refm", "in_ck")

SUMMARY_COLUMNS = ("channel", "mined", "reached", "unreached", "pct_reached", "edges",
                   "edges_exact", "edges_closes", "edges_mentions",
                   "edges_in_ledger", "edges_in_refm", "edges_in_ck", "note")


class LinkAdapter(IAdapter):
    """
    Channel Linkage: resolve mined discourse to the commits it refers to.

    A DERIVATION, NOT A MINER. It reaches no network and reads no repository -- it joins files
    the other stages already wrote. Everything it emits is recomputable from its inputs.

    RE-RUNNING OVERWRITES. THIS IS DELIBERATE AND IT DIFFERS FROM EVERY OTHER STAGE.

        The miners are append-only and resumable because mining is slow, interruptible, and
        expensive to repeat. Linkage is none of those: it is a whole-corpus join that finishes
        in seconds and is deterministic, so a partial result has no value and resuming one
        would be more machinery than the work is worth.

        Appending would be worse than useless -- a second run would double every edge. The
        output is therefore written to a temporary file and renamed over the target, which also
        means an interrupted run leaves the previous edge list intact rather than a
        half-written one.

    OUTPUT IS AN EDGE LIST, IN CSV.

        links_<repo>.csv            one row per (record, commit) link
        linkage_summary_<repo>.csv  one row per channel: mined, reached, edges, membership

        CSV rather than JSONL because the rows are narrow, flat and uniformly typed -- a table,
        not a document. Nothing here carries free text, so none of the escaping that makes CSV
        awkward for mined records applies, and the result opens in a spreadsheet.

        The edge list does NOT copy the records it links. Text, author and labels stay in
        channel_<platform>_<channel>_<repo>.jsonl and are joined on source_id when needed;
        duplicating them here would multiply the corpus and go stale the moment a channel is
        re-mined.

    LINKS TARGET THE FULL COMMIT UNIVERSE.

        A target is any commit the metadata stage recorded. in_ledger / in_refm / in_ck say
        which downstream artifacts also contain it, so narrowing the evidence to the pinned
        study grid, to refactoring commits, or to the CK snapshot grid is a filter over this
        file rather than a different run. A blank flag means that stage has not been run --
        which is not the same as the commit being absent from it.
    """

    def get_tool_name(self) -> str:
        return "Channel Linkage"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"links_{self.target_repo_path.name}.csv"

    def get_summary_path(self) -> Path:
        return config.OUTPUTS_PATH / f"linkage_summary_{self.target_repo_path.name}.csv"

    # ------------------------------------------------------------------ execution

    def execute(self) -> bool:
        repo = self.target_repo_path.name
        print(f"--- 🔗 Starting {self.get_tool_name()} ---")

        try:
            index = LinkIndex(repo)
        except LinkageInputError as e:
            print(f"❌ {e}")
            return False

        for line in index.describe_inputs():
            print(f"   {line}")

        if not index.prs and not index.issues and not index.commits:
            print("   ⚠️  No channel records to link. Mine a channel first:")
            print("      quarry --repo <project> --stage channel --platform github --channel all")
            return False

        edges = self._collect(index)
        edges = self._dedupe(edges)
        edges.sort(key=lambda e: (e.source_channel, e.source_id, e.target_sha, e.route))

        ok = self._write_links(edges, index)
        summary = self._summarise(edges, index)
        self._print_summary(summary, index)
        return self._write_summary(summary) and ok

    def _collect(self, index: LinkIndex) -> List[LinkEdge]:
        """
        Run pass 1, index its results by number, then run pass 2.

        The intermediate index is what lets a comment inherit its parent's links without
        resolving the parent a second time.
        """
        producers = all_producers()
        edges: List[LinkEdge] = []

        for producer in (p for p in producers if p.pass_number == 1):
            found = list(producer.produce(index))
            print(f"   {producer.name}: {len(found):,} edge(s)")
            edges.extend(found)

        by_number: Dict[int, List[LinkEdge]] = defaultdict(list)
        for e in edges:
            by_number[e.resolved_via].append(e)
        index.number_edges = by_number

        for producer in (p for p in producers if p.pass_number == 2):
            found = list(producer.produce(index))
            print(f"   {producer.name}: {len(found):,} edge(s)")
            edges.extend(found)

        return edges

    @staticmethod
    def _dedupe(edges: List[LinkEdge]) -> List[LinkEdge]:
        """
        One row per distinct link.

        The same edge can be found twice with different reference strengths -- a pull request
        body that both closes and mentions an issue, or two commits reaching the same place.
        The strongest kind wins, chosen by rank rather than by whichever was produced first, so
        the result does not depend on producer order.
        """
        best: Dict[tuple, LinkEdge] = {}
        for e in edges:
            current = best.get(e.key)
            if current is None or REF_RANK.get(e.ref_kind, 9) < REF_RANK.get(current.ref_kind, 9):
                best[e.key] = e
        return list(best.values())

    # ------------------------------------------------------------------ output

    def _write_links(self, edges: List[LinkEdge], index: LinkIndex) -> bool:
        return self._atomic_csv(
            self.get_output_path(), LINK_COLUMNS,
            [self._row(e, index) for e in edges],
            f"{len(edges):,} edge(s)")

    def _row(self, e: LinkEdge, index: LinkIndex) -> list:
        m = index.membership(e.target_sha)
        return [e.source_channel, e.source_id, e.resolved_via, e.target_sha,
                e.route, e.ref_kind, int(e.is_exact),
                self._flag(m["in_ledger"]), self._flag(m["in_refm"]), self._flag(m["in_ck"])]

    @staticmethod
    def _flag(value) -> str:
        """Blank means the stage has not run; 0 means it ran and does not contain the commit."""
        return "" if value is None else str(int(value))

    def _write_summary(self, summary: List[dict]) -> bool:
        return self._atomic_csv(
            self.get_summary_path(), SUMMARY_COLUMNS,
            [[row.get(c, "") for c in SUMMARY_COLUMNS] for row in summary],
            f"{len(summary)} channel(s)")

    @staticmethod
    def _atomic_csv(path: Path, columns, rows, what: str) -> bool:
        """
        Write, then rename over the target.

        A crash before the rename leaves the previous file intact; a crash after leaves the new
        one. There is no state in which the edge list is half replaced -- which matters more
        here than for an append-only miner, because a truncated CSV looks like a complete one
        with fewer links.

        newline="" is required by the csv module: without it every row is followed by a blank
        one on Windows.
        """
        temp = path.with_suffix(".tmp")
        try:
            with open(temp, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(rows)
            os.replace(temp, path)
            print(f"   📄 {path.name}: {what}")
            return True
        except OSError as e:
            print(f"   ❌ Could not write {path.name}: {e}")
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # ------------------------------------------------------------------ summary

    def _summarise(self, edges: List[LinkEdge], index: LinkIndex) -> List[dict]:
        """
        Per channel: how much was mined, how much reached a commit, and how many links exist.

        REACHED AND EDGES ARE DIFFERENT NUMBERS and both are reported. A record with three
        links is one reached record and three edges; a coverage figure that silently mixed them
        would be uninterpretable.
        """
        mined = {
            "github.pr": len(index.prs),
            "github.issue": len(index.issues),
            "github.pr_review": len(index.reviews),
            "github.comment": len(index.comments),
        }
        notes = {
            "github.pr": f"{len(index.prs) - len(index.PR_COMMIT):,} never merged"
                         if index.prs else "",
        }

        by_channel: Dict[str, List[LinkEdge]] = defaultdict(list)
        for e in edges:
            by_channel[e.source_channel].append(e)

        rows = []
        for channel, total in mined.items():
            chan_edges = by_channel.get(channel, [])
            reached = len({e.source_id for e in chan_edges})
            kinds = Counter(e.ref_kind for e in chan_edges)
            rows.append({
                "channel": channel,
                "mined": total,
                "reached": reached,
                "unreached": max(0, total - reached),
                "pct_reached": round(reached / total * 100, 1) if total else "",
                "edges": len(chan_edges),
                "edges_exact": sum(1 for e in chan_edges if e.is_exact),
                "edges_closes": kinds.get("closes", 0),
                "edges_mentions": kinds.get("mentions", 0),
                "edges_in_ledger": self._count_in(chan_edges, index.ledger),
                "edges_in_refm": self._count_in(chan_edges, index.refm),
                "edges_in_ck": self._count_in(chan_edges, index.ck),
                "note": notes.get(channel, ""),
            })
        return rows

    @staticmethod
    def _count_in(edges: List[LinkEdge], membership) -> object:
        return "" if membership is None else sum(1 for e in edges if e.target_sha in membership)

    def _print_summary(self, summary: List[dict], index: LinkIndex) -> None:
        print(f"\n   {'CHANNEL':<20}{'MINED':>10}{'REACHED':>10}{'%':>8}{'EDGES':>10}"
              f"{'IN LEDGER':>12}")
        print("   " + "-" * 70)
        for r in summary:
            pct = f"{r['pct_reached']}" if r["pct_reached"] != "" else "-"
            ledger = r["edges_in_ledger"]
            print(f"   {r['channel']:<20}{r['mined']:>10,}{r['reached']:>10,}{pct:>8}"
                  f"{r['edges']:>10,}{(ledger if ledger != '' else '-'):>12}")
            if r["note"]:
                print(f"      {r['note']}")
        if index.dropped_absent:
            print(f"\n   {index.dropped_absent:,} reference(s) named a commit absent from the "
                  f"clone; not linked.")
