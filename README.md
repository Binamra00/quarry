# Quarry

**A release-level mining pipeline for software repository analysis.**

Quarry extracts a linked, reproducible dataset from a Java repository's history: the commits
that changed it, the refactorings developers applied, the structural shape of the code at each
release, and the discussion surrounding those changes in issues, pull requests and reviews.

Five independent evidence streams, mined into one corpus that can be joined on commit, file and
release.

---

## Contents

1. [What Quarry is for](#what-quarry-is-for)
2. [Installation](#installation)
3. [Getting started](#getting-started)
4. [How it works](#how-it-works)
5. [The stages](#the-stages)
6. [Scope: choosing which commits](#scope-choosing-which-commits)
7. [Trigger channels](#trigger-channels)
8. [Output](#output)
9. [Reliability](#reliability)
10. [Architecture](#architecture)
11. [Configuration](#configuration)
12. [Troubleshooting](#troubleshooting)
13. [License and citation](#license-and-citation)

---

## What Quarry is for

Most repository-mining work begins the same way: assemble a corpus, run three or four tools
over it, and discover weeks later that their outputs do not line up. One tool walked the main
branch, another walked every branch. One was interrupted and silently resumed short. A GitHub
channel stopped at 30,000 records without reporting an error. The analysis that follows is
built on a dataset nobody can fully account for.

Quarry exists to make that dataset accountable. It coordinates the tools, pins them all to the
same set of commits, records every failure as data rather than discarding it, and resumes
exactly where it stopped after any interruption.

**Use it to:**

- Build a longitudinal dataset of refactoring activity across a project's releases.
- Measure how a codebase's structure changed between versions, at class and method level.
- Link code changes to the issues, pull requests and review comments that surrounded them.
- Assemble a multi-project corpus where every project was mined identically.
- Reproduce someone else's mining run, or your own, months later and get the same result.

**It is mining infrastructure.** Quarry produces data. It does not model, score, or predict —
those are analyses you build on top of its output.

---

## Installation

### Requirements

| | |
| :--- | :--- |
| **Python** | 3.9 or newer |
| **Java** | 17 or newer — RefactoringMiner and CK both run on the JVM. Verify with `java -version`. |
| **Git** | available on `PATH` |
| **GitHub token** | only for GitHub channels. Set `GITHUB_TOKEN` in `.env`. |

Analysis tools are downloaded automatically on first use. You do not install them yourself.

### Install

```bash
git clone https://github.com/Binamra00/quarry.git
cd quarry

python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS

python -m pip install -e .
quarry --help
```

If `quarry` is not found afterwards, see [Troubleshooting](#troubleshooting).

---

## Getting started

Mine a small project end to end:

```bash
# 1. Establish the commit universe. A URL is cloned into the workspace on first use.
quarry --repo https://github.com/danilofes/refactoring-toy-example.git --stage meta

# 2. Extract refactorings and structural metrics.
quarry --repo <project> --stage refm --full
quarry --repo <project> --stage ck

# 3. Read back what was produced.
quarry --repo <project> --stage report
```

After the first run, refer to the project by the folder name it was cloned into.

`quarry --help` prints the complete flag matrix, the available channels, and worked examples.
That help is generated from the same specification the tool validates against, so it can never
describe a combination the tool would reject.

---

## How it works

A Quarry run is five decisions, in order. Only the first two are always required.

| | Decision | Flag |
| :--- | :--- | :--- |
| 1 | Which repository | `--repo <folder-name \| github-url>` |
| 2 | Which miner | `--stage meta\|ledger\|refm\|ck\|channel\|report` |
| 3 | Which scope | `--full` · `--universe FILE` · `--version TAG` · `--sample FILE` |
| 4 | *(channels only)* Which platform | `--platform git\|github` |
| 5 | *(channels only)* Which channels | `--channel commits\|issues,prs\|all` |

**One miner per run.** There is no combined stage. Each miner writes its own output and tracks
its own progress, so they run independently and — after `meta` — in any order. A failure in one
never costs you the others.

**Every miner resumes.** Re-run the identical command and it continues from where it stopped:
after an interrupt, a crash, a reboot, or an exhausted API quota. Nothing is mined twice.

**Invalid commands fail immediately.** Flag combinations are checked against a declared
specification before any repository is touched, and every problem in a command is reported at
once rather than one run at a time.

---

## The stages

| Stage | Extracts | Notes |
| :--- | :--- | :--- |
| `meta` | Git lineage and repository metadata | Run first — it establishes the commit universe every other stage joins on |
| `ledger` | Per-commit evolutionary features: churn, authorship, co-change | |
| `refm` | Refactoring operations per commit, via RefactoringMiner | Produces a completion report automatically |
| `ck` | Class- and method-level structural metrics per snapshot, via CK | The heaviest stage; pair with `--sample` |
| `channel` | Commits, issues, pull requests, review comments, issue comments | Requires `--platform` and `--channel` |
| `report` | Nothing — summarises what the other stages produced | Read-only |

---

## Scope: choosing which commits

`ledger`, `refm` and the git commit channel walk history, so they must be told which commits to
walk. There is no default, deliberately.

**`--universe adapter_universe_<project>.json`** — a pinned set of commits. Use this for any
dataset you intend to analyse or publish. It is the only way to guarantee that every stage
walked the same history, which is what makes their outputs joinable.

**`--full`** — every commit reachable in the clone. Not frozen: two runs on different days walk
different histories, and the result will not align with anything mined against a pinned
universe. Intended for verification and exploration; the tool prints a warning.

**`--version <tag>`** — check out a single tag or commit and mine only that point.

`ck` is scoped differently. Because it measures snapshots rather than walking commits, it takes
**`--sample rel_hist_<project>.json`** to restrict it to a release grid.

The requirement is strict because the failure it prevents is silent. An unpinned run succeeds,
its records look correct, and they simply never match the ones mined against the grid — no
error, no warning, just a join that quietly loses rows.

---

## Trigger channels

A channel is a single source of developer discourse. Each is mined into its own file with its
own progress state, so one failing leaves the rest untouched.

| Platform | Channels | Requires |
| :--- | :--- | :--- |
| `git` | `commits` | Nothing — reads the local clone |
| `github` | `issues`, `prs`, `pr_reviews`, `comments` | `GITHUB_TOKEN` |

```bash
quarry --repo myproject --stage channel --platform github --channel issues,prs
quarry --repo myproject --stage channel --platform github --channel all --batch 200
quarry --repo myproject --stage channel --platform git --channel commits \
       --universe adapter_universe_myproject.json
```

Only **closed** issues and pull requests are mined. An open issue has no resolving commit, so it
cannot be linked to code.

Review comments are the only text channel with native file linkage: the API reports the file
and line a comment was written against, so it reaches code without any reference resolution at
all.

### Two API limits Quarry handles for you

Neither is documented prominently by GitHub, and one fails silently.

- **`/issues` refuses offset pagination past the 10,000th item** with HTTP 422. Quarry follows
  the cursor in the response's `Link` header rather than constructing page numbers, which
  bypasses the limit entirely.
- **`/issues/comments` stops paginating at 30,000 items without reporting anything.** It simply
  returns as though the collection ended. On one large project this truncated the channel six
  years early with no error raised. Quarry detects the stall and restarts the walk filtered to
  records newer than the last one seen, repeating until a window yields nothing new.

Listings are always retrieved in ascending creation order. Sorting by update time would reorder
items whenever anything is edited, so a run resumed the next day could skip records it had
never seen.

---

## Output

Results are written to `workspace_data/outputs/`; release-grid definitions live in
`workspace_data/versions/`.

| Artifact | Format | Contents |
| :--- | :--- | :--- |
| `ck_metrics_<project>.jsonl` | JSONL | One record per snapshot: status, timestamp, class and method counts, nested metrics |
| `channel_<platform>_<channel>_<project>.jsonl` | JSONL | One record per channel item, in a unified shape across platforms |
| `adapter_universe_<project>.json` | JSON | The pinned commit universe |
| `rel_hist_<project>.json` | JSON | The frozen snapshot grid — the release points to be measured |
| `<project>_release_manifest.json` | JSON | Admission thresholds, rejected tags, SHA aliases |
| `*_execution_<project>.log` | Text | Per-run diagnostics: failures, timeouts, empty results |

All record streams are append-only JSONL, so a run can be interrupted at any point without
corrupting what came before, and large projects never require holding a dataset in memory.

Run `quarry --repo <project> --stage report` to summarise what is present.

### Failures are data

A snapshot that crashed, timed out, produced nothing, or could not be checked out still
receives a record. This is what makes an incomplete dataset visible rather than merely short.

| Status | Meaning | Retried on next run |
| :--- | :--- | :--- |
| `success` | Classes and methods extracted | No |
| `empty_methods` | Classes extracted, no methods — the tool ran and answered | No |
| `empty_output` | The tool succeeded and produced an empty result | No |
| `missing_output` | The tool succeeded but wrote no file | Yes |
| `crash` / `timeout` | The tool failed | Yes |
| `checkout_failed` | The commit could not be checked out | Yes |

The first three describe the *snapshot* and are final. The last three describe the *run* and are
re-attempted automatically. A re-attempt appends a new record for the same commit, so **the last
record for a commit is the current one** — group by commit and take the final occurrence.

Every run ends with a summary line (`success=399 | empty_output=143`), so an incomplete dataset
is visible without reading a log file.

---

## Reliability

Long mining runs are interrupted. Quarry is built on the assumption that they will be.

**Progress is derived from output, not tracked separately.** Most of the pipeline reconstructs
what it has done by reading its own results: a unit appears in the output if and only if it was
completed. There is no separate progress file that can disagree with the data, and therefore no
window in which a process killed between writing a record and saving its progress causes that
work to be repeated and duplicated.

**Where a separate state file is unavoidable, it is written atomically.** Channels are the
exception: their position in a paginated API, the time window in progress, and the moment a
quota resets exist nowhere in the mined records. That state is written to a temporary file and
renamed over the target, so an interrupted write cannot corrupt progress already earned.

**API quotas pause rather than fail.** When a GitHub quota is exhausted, the run stops cleanly,
reports when the quota returns, and the next invocation continues from the stored cursor.

**Transient failures are retried; real ones are reported.** Dropped connections, timeouts and
server errors are retried with backoff. Burst throttling is waited out rather than treated as
an error. Authentication failures and missing repositories stop the run with a message naming
the cause.

**The workspace is always restored.** Stages that check out historical commits return the
repository to its original state on exit, including after a crash.

---

## Architecture

Quarry is built as a set of interchangeable components behind stable interfaces. This is not
incidental: the reason a new data source can be added without touching the execution machinery,
and the reason a validation rule cannot drift out of step with the documentation, are both
consequences of the structure below.

| Pattern | Applied to | Effect |
| :--- | :--- | :--- |
| **Specification** | The stage/flag matrix | Valid flag combinations are declared as data. The validator enforces that data and `--help` renders it, so the documentation and the behaviour cannot disagree. |
| **Adapter** | External tools | A JVM tool, a Python library and an HTTP API are driven through one interface, so the pipeline treats them identically. |
| **Strategy** | Channel sources | A source knows how to reach one platform and nothing else. Adding a platform adds a source; nothing else changes. |
| **Factory Method** | Stage construction | One place assembles the work a stage implies, with lazy loading — a channel run never loads the structural-metrics tool. |
| **Command** | Units of work | Miners and reports are queued and executed identically, so the runner needs no special cases. |
| **Composite** | Execution | Several units run under one invocation with a circuit breaker: a failure marks the run unhealthy without denying independent work its chance to progress. |
| **Facade** | Environment setup | Provisioning, acquisition, synchronisation and revision pinning are a single call. |
| **Template Method** | Reporting | The report lifecycle is defined once and specialised per data source. |
| **Value Object** | Run configuration | A run is an immutable value rather than a bag of command-line arguments, so the pipeline can be driven from a script or notebook as easily as a terminal. |

Two principles run through the whole system: **failures are recorded rather than swallowed**,
and **recording a failure is not the same as completing the work**. Together they mean an
incomplete dataset announces itself, and re-running the command repairs it.

### Tools

| Tool | Version | Role |
| :--- | :--- | :--- |
| RefactoringMiner | 3.1.3 | Refactoring operations per commit |
| CK | 0.7.0 | Class- and method-level structural metrics |
| Git CLI | any | History traversal, checkout, universe resolution |
| GitHub REST API | 2022-11-28 | Issues, pull requests, reviews, comments |

Versions, download URLs and expected checksums are all configurable.

---

## Configuration

Create a `.env` file in the project root:

```ini
GITHUB_TOKEN=ghp_...
QUARRY_HOME=E:\quarry_workspace     # optional; defaults to ./workspace_data
CK_VERSION=0.7.0
RM_VERSION=3.1.3
CK_TIMEOUT=3600                     # seconds per snapshot
JAVA_XMX=4g                         # heap for structural analysis; large projects need headroom
```

`QUARRY_HOME` relocates the entire workspace — clones, downloaded tools, outputs and logs — which
is useful when the project lives on one drive and the data belongs on another.

### Controlling run length

`--batch N` stops a stage after N records and exits cleanly; the next run resumes. It is the
practical way to try a GitHub channel against a few hundred real records without spending an
hour of quota, or to run a long extraction in sessions. `--batch 0` removes the limit.

---

## Troubleshooting

**`'quarry' is not recognized` after a successful install.**
Read pip's warnings — it names the directory it installed the command into. This usually means
the virtual environment was not active, in which case pip will also have said *"Defaulting to
user installation"*. Confirm with:

```bash
python -c "import sys; print(sys.prefix == sys.base_prefix)"
```

`True` means no environment is active. Activate it and reinstall with `python -m pip install -e .`
— using `python -m pip` guarantees you are using the pip belonging to that interpreter.

**An invocation that always works**, with no installation and no changes to `PATH`:

```bash
python -m pipeline.main --help
```

**GitHub mining is slow or fails.** Without a token the API allows 60 requests an hour, against
5,000 authenticated. Quarry warns at startup when it is running unauthenticated.

**A stage reports a missing Python package.** Reinstall with `python -m pip install -e .`, which
resolves all runtime dependencies.

**Structural analysis fails on a large project.** Increase `JAVA_XMX` and, if snapshots are
timing out, `CK_TIMEOUT`.

---

## License and citation

Released under the MIT License.

If you use Quarry in published work, please cite the release archive for the version you used.
