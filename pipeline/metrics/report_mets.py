import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline import config
from pipeline.metrics.temp_mets import BaseMetrics


class ReportMetrics(BaseMetrics):
    """
    Universe Report (Phase: report).

    A pure reader. It mines NOTHING -- it reads the artifacts the adapters already
    produced and answers two questions:

      1. What is the study universe?  (timeline + total commit count, from metadata)
      2. Did the miners cover it?     (per-adapter counts vs the universe, with a
                                       verification verdict)

    This exists because "how big is the repo / did everything mine cleanly" was
    previously answered by re-walking the entire history on every stage -- a second,
    redundant mine. The metadata adapter is the single source of truth for the commit
    universe; the ledger and RefactoringMiner report how much of it they covered. This
    module just reads those three files and cross-checks them.

    Reads:
      commit_lineage_<repo>.jsonl   (metadata: the full universe + timestamps)
      ledger_history_<repo>.jsonl   (ledger coverage)
      refactorings_<repo>.jsonl     (RefactoringMiner coverage; Java-touching subset)
      adapter_universe_<repo>.json  (optional: declared EXPLICIT universe, if pinned)

    Runs after mining, as its own stage. It never re-mines.
    """

    def get_tool_name(self) -> str:
        return "Universe Report"

    def get_output_path(self) -> Path:
        return config.OUTPUTS_PATH / f"universe_report_{self.target_repo_path.name}.json"

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _count_lines(path: Path) -> int:
        """Number of non-blank lines (records) in a JSONL file. 0 if absent."""
        if not path.exists():
            return -1                       # -1 == "adapter did not run", distinct from 0 records
        n = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n

    @staticmethod
    def _metadata_timeline(path: Path) -> Dict[str, Any]:
        """
        Read the metadata lineage stream once: total commits and min/max timestamp.
        O(1) memory -- tracks only running min/max, does not hold the file.
        """
        if not path.exists():
            return {"present": False}
        total, tmin, tmax = 0, None, None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                ts = rec.get("timestamp")
                if ts is None:
                    continue
                try:
                    ts = int(ts)
                except (TypeError, ValueError):
                    continue
                tmin = ts if tmin is None or ts < tmin else tmin
                tmax = ts if tmax is None or ts > tmax else tmax

        out = {"present": True, "total_commits": total}
        if tmin is not None and tmax is not None:
            d0 = datetime.fromtimestamp(tmin, tz=timezone.utc)
            d1 = datetime.fromtimestamp(tmax, tz=timezone.utc)
            out.update(start_date=d0.date().isoformat(),
                       end_date=d1.date().isoformat(),
                       age_days=(d1 - d0).days)
        return out

    def _declared_universe(self) -> Optional[Dict[str, Any]]:
        """The pinned EXPLICIT universe file, if one exists. None -> FULL-mode run."""
        path = config.universe_file(self.target_repo_path.name)
        if not path.exists():
            path = config.OUTPUTS_PATH / path.name
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return {
            "mode": "EXPLICIT",
            "head_commits": data.get("head_commits"),
            "n_dangling": len(data.get("near_mainline_shas", [])),
            "universe_commits": data.get("universe_commits"),
        }

    # ------------------------------------------------------------------ template hooks

    def load_data(self) -> Dict[str, Any]:
        name = self.target_repo_path.name
        return {
            "meta_path":   config.OUTPUTS_PATH / f"commit_lineage_{name}.jsonl",
            "ledger_path": config.OUTPUTS_PATH / f"ledger_history_{name}.jsonl",
            "refm_path":   config.OUTPUTS_PATH / f"refactorings_{name}.jsonl",
        }

    def calculate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        timeline    = self._metadata_timeline(context["meta_path"])
        ledger_n    = self._count_lines(context["ledger_path"])
        refm_n      = self._count_lines(context["refm_path"])
        declared    = self._declared_universe()

        meta_n = timeline.get("total_commits") if timeline.get("present") else None

        # --- verification: cross-check coverage against the universe ---
        checks = []

        def add(name, ok, detail):
            checks.append({"check": name, "ok": ok, "detail": detail})

        if meta_n is None:
            add("metadata_present", False,
                "commit_lineage_<repo>.jsonl missing -- run --stage meta first")
        else:
            # In FULL mode the ledger walks the same --all universe as metadata, so counts match.
            # In EXPLICIT mode they intentionally differ (ledger walks the pinned grid), so this
            # check only applies when no pinned universe is declared.
            if ledger_n >= 0:
                if declared is None:
                    add("ledger_covers_universe", ledger_n == meta_n,
                        f"ledger {ledger_n} vs metadata {meta_n} "
                        f"({'match' if ledger_n == meta_n else 'MISMATCH'})")
                else:
                    add("ledger_pinned_universe", True,
                        f"ledger {ledger_n} (EXPLICIT universe; not compared to full metadata)")
            if refm_n >= 0 and ledger_n >= 0:
                # RefactoringMiner only mines Java-touching commits, so it is always a subset.
                add("refm_subset_of_ledger", refm_n <= ledger_n,
                    f"refm {refm_n} <= ledger {ledger_n} "
                    f"({'ok' if refm_n <= ledger_n else 'VIOLATION: refm exceeds ledger'})")

        all_ok = all(c["ok"] for c in checks) if checks else False

        return {
            "project_name": self.target_repo_path.name,
            "generated": datetime.now(timezone.utc).isoformat(),
            "universe": {
                "mode": declared["mode"] if declared else "FULL",
                "metadata_total_commits": meta_n,
                **({"declared": declared} if declared else {}),
            },
            "timeline": {k: timeline[k] for k in ("start_date", "end_date", "age_days")
                         if k in timeline},
            "coverage": {
                "metadata": meta_n,
                "ledger":   ledger_n if ledger_n >= 0 else None,
                "refm":     refm_n if refm_n >= 0 else None,
            },
            "verification": {"all_passed": all_ok, "checks": checks},
        }

    def print_report(self, m: Dict[str, Any]):
        u, t, c, v = m["universe"], m["timeline"], m["coverage"], m["verification"]

        def fmt(n):
            return "—" if n is None else f"{n:,}"

        print(f"Universe Report: {m['project_name']}")
        print(f"├── [Mode]     {u['mode']}")
        if t:
            print(f"├── [Timeline] {t.get('start_date','?')} → {t.get('end_date','?')}"
                  f"  ({t.get('age_days','?')} days)")
        print(f"│")
        print(f"├── [Universe] metadata (source of truth): {fmt(u['metadata_total_commits'])} commits")
        print(f"├── [Coverage] ledger mined:               {fmt(c['ledger'])}")
        print(f"├── [Coverage] refm mined (java-touching):  {fmt(c['refm'])}")
        print(f"│")
        verdict = "✅ PASS" if v["all_passed"] else "❌ CHECK"
        print(f"└── [Verify]   {verdict}")
        for chk in v["checks"]:
            mark = "✓" if chk["ok"] else "✗"
            print(f"      {mark} {chk['check']}: {chk['detail']}")
        print("------------------------------------------")
