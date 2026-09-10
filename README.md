# Quarry

**A release-level mining pipeline for refactoring trigger analysis.**

Version 0.1.0 · Python 3.9+ · Windows, Linux, macOS

Quarry reconstructs what happened to a Java codebase between releases: which commits changed
it, which refactorings were applied, what its structure looked like at each release, and what
developers were saying in the issues, pull requests and reviews around those changes. It
produces one linked corpus from five separate evidence streams so that questions about *what
triggers a refactoring* can be asked empirically.

It is mining infrastructure. It does not rank, score, or predict anything — those are
downstream analyses that consume its output.

---

## 1. Quick start

```bash
git clone https://github.com/Binamra00/quarry.git
cd quarry

python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS

python -m pip install -e .
quarry --help
```

Then mine a small project end to end:

```bash
quarry --repo https://github.com/danilofes/refactoring-toy-example.git --stage meta
quarry --repo <folder-it-cloned-into> --stage refm   --full
quarry --repo <folder-it-cloned-into> --stage ck
quarry --repo <folder-it-cloned-into> --stage report
```

If `quarry` is not found after installing, see [Troubleshooting](#11-troubleshooting) — it is
almost always a PATH issue and there is an invocation that always works.

### Prerequisites

| | |
| :--- | :--- |
| **Python** | 3.9 or newer |
| **Java** | 17 or newer. RefactoringMiner 3.x and CK both run on the JVM. Verify with `java -version`. |
| **Git** | on `PATH`. Quarry shells out to the `git` CLI for history walking and checkouts. |
| **GitHub token** | only for the `github` channels. Put `GITHUB_TOKEN` in `.env`. |

Analysis tools are downloaded on first use into `workspace_data/tools/`; you do not install
them yourself.

---

## 2. How to use it

Five decisions, in order. Only the first two are always needed.

| | decision | flag |
| :--- | :--- | :--- |
| 1 | which repository | `--repo <folder-name \| github-url>` |
| 2 | which miner | `--stage meta\|ledger\|refm\|ck\|channel\|report` |
| 3 | which scope | `--full` · `--universe FILE` · `--version TAG` · `--sample FILE` |
| 4 | *(channel only)* which platform | `--platform git\|github` |
| 5 | *(channel only)* which channels | `--channel commits\|issues,prs\|all` |

**One miner per run.** There is no `all` stage. Each miner writes its own output and keeps its
own progress, so they run one at a time and, after `meta`, in any order.

**Every miner resumes.** Re-run the identical command and it continues where it stopped —
after an interrupt, a crash, or an exhausted API quota. Nothing is mined twice.

`quarry --help` prints the full flag matrix, the available channels, and worked examples. That
help text is generated from the same table the validator enforces, so it cannot describe a
combination the tool would reject.

---

## 3. The stages

| stage | what it does | run it |
| :--- | :--- | :--- |
| `meta` | Git lineage and repository metadata. Establishes the commit universe everything else joins on. | first |
| `ledger` | Per-commit evolutionary features: churn, authorship, co-change. | after `meta` |
| `refm` | RefactoringMiner — refactoring operations per commit. Emits its own completion report. | after `meta` |
| `ck` | CK structural metrics at each snapshot. The heaviest miner by far; pair with `--sample`. | after `meta` |
| `channel` | Trigger channels — commits, issues, pull requests, review comments, issue comments. | any time |
| `report` | Read-only summary of what the miners produced. Mines nothing. | last |

### Scope, and why it is not optional

`ledger`, `refm` and the git commit channel walk git history, so they **must** be told which
commits. There is no default:

- `--universe adapter_universe_<repo>.json` — the pinned study grid. **Use this for anything
  a study depends on.** It is the only way to guarantee every miner walked the same commits.
- `--full` — every commit reachable in the clone. Not frozen: two runs on different days walk
  different histories, and the output will not join a pinned run. Verification and exploration
  only; the tool prints a warning.

An unstated universe is how outputs silently stop joining — the run succeeds, the records look
fine, and they simply never match. Hence the hard requirement rather than a default.

`ck` is scoped differently, by `--sample rel_hist_<repo>.json`, because it measures snapshots
rather than walking commits.

---

## 4. Trigger channels

A channel is one source of developer discourse. Each is mined into its own file with its own
resumable state, so one failing leaves the others intact.

| platform | channels | needs |
| :--- | :--- | :--- |
| `git` | `commits` | nothing — reads the local clone |
| `github` | `issues`, `prs`, `pr_reviews`, `comments` | `GITHUB_TOKEN` in `.env` |

```bash
quarry --repo checkstyle --stage channel --platform github --channel issues,prs
quarry --repo checkstyle --stage channel --platform github --channel all --batch 200
quarry --repo checkstyle --stage channel --platform git --channel commits \
       --universe adapter_universe_checkstyle.json
```

**Only closed issues and pull requests are mined.** An open issue has no resolving commit, so
it cannot reach a file and would be discarded at linkage anyway.

`--universe` applies only to the git channel. Issues and comments are not commits, so a commit
SHA cannot bound them; the pinned universe still constrains them, but at **linkage** — a record
whose reference falls outside it never joins the ledger.

### Two API failure modes worth knowing about

Both are handled, and neither is obvious:

- `/issues` refuses offset pagination past the 10,000th item with HTTP 422. Quarry follows the
  `Link` header's cursor rather than constructing `page=N`, which bypasses the cap.
- `/issues/comments` **silently** stops offering `rel="next"` at 30,000 items and returns as
  though the collection ended. On one project that truncated the channel at 2020 while the
  repository was active into 2026, with no error raised. Quarry detects the stall and restarts
  the walk with `since` set to the newest record already seen, repeating until a window
  produces nothing newer.

Listings are always requested `sort=created&direction=asc`. Sorting by update time would
reorder items whenever anything is edited, so a resumed run could skip records it never saw.
Page-based resumption is only sound under ascending creation order.

---

## 5. Output

Everything lands in `workspace_data/outputs/`, except grid artifacts, which live in
`workspace_data/versions/`.

| artifact | format | contents |
| :--- | :--- | :--- |
| `ck_metrics_<repo>.jsonl` | JSONL | One record per snapshot: status, timestamp, class and method counts, nested CK metrics. |
| `channel_<platform>_<channel>_<repo>.jsonl` | JSONL | One record per mined channel item, in a unified shape across platforms. |
| `channel_status_<platform>_<channel>_<repo>.json` | JSON | Pagination cursor, time window, quota reset. Channels only — see §6. |
| `adapter_universe_<repo>.json` | JSON | The pinned commit universe. Produced by the release-tag mining notebook, **not** by any stage. |
| `rel_hist_<repo>.json` | JSON | The frozen snapshot grid: the study's observation points. |
| `<repo>_release_manifest.json` | JSON | Admission thresholds, rejected tags, SHA aliases, grid rule. |
| `*_execution_<repo>.log` | text | Per-run diagnostics: failures, timeouts, empty outputs, checkout errors. |

`quarry --repo <name> --stage report` reads these back and summarises what is present.

### CK records a status for every snapshot

A snapshot that crashed, timed out, produced no CSV, or could not be checked out still gets a
record. That is what makes a partial grid visible instead of silently short:

| status | meaning | re-mined? |
| :--- | :--- | :--- |
| `success` | classes and methods parsed | no |
| `empty_methods` | classes parsed, no methods — CK ran and answered | no |
| `empty_output` | CK exited 0 and wrote a parseable file containing nothing | no |
| `missing_output` | CK exited 0 and wrote no file | **yes** |
| `crash` / `timeout` | CK failed | **yes** |
| `checkout_failed` | the commit could not be checked out | **yes** |

The last three describe the **run**, not the snapshot, so they are re-attempted on the next
invocation. A re-attempt appends a second record for the same SHA: **the last record for a SHA
is the current one.** Any consumer must group by `sha` and take the final occurrence — counting
lines over-counts once a retry has happened.

Each run ends with a tally (`success=399 | empty_output=143`) so a partial grid is visible
without reading the log.

---

## 6. How resumption works

Two mechanisms, and the difference between them is a difference in kind.

**Miners reconstruct progress from their own output** (`OutputDerivedState`). A unit appears in
the JSONL if and only if it was completed, so there is no second record to disagree with the
first. The failure this avoids is specific: a miner writes a record, is killed before a state
file is flushed, and the next run re-processes work already on disk — appending a duplicate.
Flushing on interrupt narrows that window but cannot close it, because `SIGKILL`, an OOM kill
and a power loss do not run handlers.

**Channels need a state file** (`ChannelStateManager`) because their progress involves things
the output cannot hold: how far pagination got, which time window is in progress, and when an
API quota resets. Those exist nowhere in the mined records. State is written atomically
(temp file + rename), with a short retry for the Windows case where a background scanner holds
the destination open.

When a GitHub quota runs out, the run stops cleanly, reports when it returns, and the next
invocation continues from the stored cursor.

---

## 7. Project layout

```text
quarry/
├── pyproject.toml               packaging + the `quarry` entry point
├── requirements.txt             checkout-and-run alternative to pip install -e .
├── .env                         GITHUB_TOKEN, QUARRY_HOME, tool version overrides
│
├── scripts/
│   └── smoke_test.py            runs every command combination the CLI accepts
│
├── tests/                       pytest suite
│
└── pipeline/
    ├── __init__.py              forces UTF-8 streams before anything prints
    ├── __main__.py              enables `python -m pipeline`
    ├── main.py                  entry point: six steps, no decisions
    ├── config.py                paths, tool versions, channel platforms
    │
    ├── cli/                     the command line
    │   ├── spec.py              STAGES — the stage/flag table, as data
    │   ├── plan.py              RunPlan — one invocation, as a value
    │   ├── validate.py          enforces the table; reports every violation at once
    │   └── parser.py            argparse -> RunPlan
    │
    ├── runtime/
    │   ├── workspace.py         provision, acquire, sync, pin
    │   └── runner.py            executes commands; circuit breaker; exit code
    │
    ├── adapters/                one per tool (metadata, ledger, refm, ck, channel)
    ├── channels/                source strategies per platform + the channel contract
    ├── platforms/               github_client.py — auth, pagination, quota, backoff
    ├── commands/                Command wrappers for miners and reports
    ├── factories/               adapter_fact.py — (plan, repo) -> commands
    ├── metrics/                 report generation
    ├── state/                   output_state.py — output-derived progress
    ├── scope.py                 release-grid sampling
    ├── acquisition.py           repository acquisition and sync
    └── utils/                   subprocess, console output, tool provisioning
```

`main.py` is genuinely a facade now:

```python
plan = StageValidator().enforce(CliParser().parse())
plan.announce()
repo = Workspace.prepare(plan)
commands = PipelineFactory.create_commands(plan, repo)
return PipelineRunner(commands).run()
```

---

## 8. Design

| pattern | where | why |
| :--- | :--- | :--- |
| **Specification** | `cli/spec.py` | The stage/flag matrix is data the validator reads and the help renders, so the two cannot drift apart. |
| **Value Object** | `cli/plan.py` | `RunPlan` decouples the pipeline from argparse — it can be driven from a notebook. |
| **Facade** | `runtime/workspace.py`, `main.py` | A fixed setup sequence with no decisions in it. |
| **Command** | `commands/` | Miners and reports queue identically; the runner needs no special cases. |
| **Composite / Invoker** | `runtime/runner.py` | Circuit breaker rather than fail-fast: one failing channel does not deny the others their progress. |
| **Factory Method** | `factories/adapter_fact.py` | One construction site for every stage, with lazy imports so a channel run never loads CK. |
| **Adapter** | `adapters/` | `IAdapter` standardises tools as different as a JAR, a Python library and an HTTP API. |
| **Strategy** | `channels/`, `utils/ui_strategy.py` | A channel source knows how to reach one platform; the adapter is identical across all of them. |
| **Template Method** | `metrics/temp_mets.py` | `BaseMetrics` defines the report lifecycle. |

Two rules the code holds to throughout: **failures are recorded, not swallowed**, and
**recording a failure is not the same as completing the work**.

---

## 9. Toolchain

| tool | version | role |
| :--- | :--- | :--- |
| **RefactoringMiner** | 3.1.3 | Refactoring operations per commit |
| **CK** | 0.7.0 | Class- and method-level structural metrics per snapshot |
| **Git CLI** | any | History walking, checkout, universe resolution |
| **GitHub REST API** | 2022-11-28 | Issues, pull requests, reviews, comments |

Versions are overridable in `.env` (`CK_VERSION`, `RM_VERSION`), as are the download URLs and
expected SHA-256 digests. Provisioning happens automatically before the first run; to trigger
it by hand:

```bash
python -m pipeline.utils.allocate_tools
```

---

## 10. Testing

### Command matrix

`scripts/smoke_test.py` runs every command Quarry accepts and every command it must refuse —
43 cases across three tiers.

```bash
python scripts/smoke_test.py --list                     # show every command
python scripts/smoke_test.py --tier local --tier reject # offline, safe any time
python scripts/smoke_test.py --tier github              # needs GITHUB_TOKEN
python scripts/smoke_test.py --dry-run                  # print, run nothing
```

- **local** — every stage against the clone, across `--full`, `--universe`, `--version`,
  `--sample` and three batch sizes.
- **github** — each of the four GitHub sources separately (they fail in different ways, so one
  combined case would hide which broke), plus `all` and a resumption pass.
- **reject** — 16 invalid combinations. A validator that quietly stops rejecting something is a
  silent regression, so the refusals are tested as rigorously as the acceptances.

Cases needing a manifest that does not exist are reported as `SKIP`, not `FAIL`: a repository
the release-grid notebook has never been run against has no pinned universe, and that is not a
bug.

The script prefers the installed `quarry` command when it is on `PATH`, and falls back to
`python -m pipeline.main`. Running it after `pip install -e .` therefore verifies the packaging
as well as the code.

### Unit and integration tests

```bash
pytest tests/ -v
pytest tests/unit/
```

---

## 11. Troubleshooting

**`'quarry' is not recognized`** after a successful install.
Read pip's own warnings — it names the directory it put `quarry.exe` in. This usually means the
virtual environment was not actually active (pip will have said *"Defaulting to user
installation"*). Check with:

```bash
python -c "import sys; print(sys.executable); print(sys.prefix == sys.base_prefix)"
```

`True` means no venv is active. Activate it, then `python -m pip install -e .` — using
`python -m pip` guarantees the pip belonging to the interpreter you just checked.

**The invocation that always works**, with no install and no PATH changes:

```bash
python -m pipeline.main --help
```

**`UnicodeEncodeError` on Windows.** Fixed in `pipeline/__init__.py`, which forces UTF-8 on
stdout and stderr before anything prints. Windows uses the ANSI code page when output is piped
rather than written to a console, and cp1252 cannot encode the emoji in the status lines — so
the tool worked by hand and died under `quarry ... > run.log`.

**GitHub runs are slow or fail.** Without `GITHUB_TOKEN` the API allows 60 requests an hour
against 5,000 authenticated. Quarry warns loudly at startup when it is unauthenticated.

**`ledger` fails with a pydriller import error.** `pip install pydriller`, or reinstall the
package — it is a declared dependency and the only miner with a third-party runtime
requirement.

---

## 12. Configuration

`.env` at the project root:

```ini
GITHUB_TOKEN=ghp_...
QUARRY_HOME=E:\quarry_workspace     # optional; defaults to ./workspace_data
CK_VERSION=0.7.0
RM_VERSION=3.1.3
CK_TIMEOUT=3600                     # seconds per snapshot
JAVA_XMX=4g                         # CK heap; large repositories need headroom
```

---

## 13. Status

Active development. The mining stages are complete and in use on a five-repository Java corpus;
the linkage and analysis layers built on top of this output live in separate notebooks.

Quarry is the mining infrastructure extracted from a thesis project on refactoring
prioritisation. The two are versioned and released separately.
