# Quarry

**A release-level mining pipeline for software repository analysis.**

Quarry extracts a linked, reproducible dataset from a Java repository's history: the commits
that changed it, the refactorings developers applied, the lines each commit changed, the
structural shape of the code at each release, and the discussion surrounding those changes in
issues, pull requests and reviews.

Independent evidence streams, mined into one corpus that can be joined on commit, file and
release.

**Used in:** *Code, Commit History and Issue/PR Discourse for Forecasting Refactoring*. Its mined
inputs ([10.5281/zenodo.24182007](https://doi.org/10.5281/zenodo.24182007)), its dataset
([10.5281/zenodo.24117444](https://doi.org/10.5281/zenodo.24117444)) and its notebooks
([refactoring-forecast-replication](https://github.com/Binamra00/refactoring-forecast-replication))
show a complete study built on Quarry. See [Mining a study](#mining-a-study).

---

## Contents

1. [What Quarry is for](#what-quarry-is-for)
2. [Installation](#installation)
3. [Getting started](#getting-started)
4. [How it works](#how-it-works)
5. [The stages](#the-stages)
6. [Scope: choosing which commits](#scope-choosing-which-commits)
7. [Mining a study](#mining-a-study)
8. [Trigger channels](#trigger-channels)
9. [Linkage](#linkage)
10. [Output](#output)
11. [Reliability](#reliability)
12. [Architecture](#architecture)
13. [Configuration](#configuration)
14. [Troubleshooting](#troubleshooting)
15. [Acknowledgements](#acknowledgements)
16. [License and citation](#license-and-citation)

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
- Link code changes to the issues, pull requests and review comments that surrounded them,
  as an edge list you can filter and join.
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

# 2. Extract refactorings, changed lines and structural metrics.
quarry --repo <project> --stage refm --full
quarry --repo <project> --stage diff --full
quarry --repo <project> --stage ck

# 3. Resolve discourse to commits, then read back what was produced.
quarry --repo <project> --stage link
quarry --repo <project> --stage report
```

After the first run, refer to the project by the folder name it was cloned into.

Most stages stop after 50 records by default and resume on the next run. That keeps a first try
short. To run a stage to completion in one go, add `--batch 0`.

`quarry --help` (or `quarry` on its own) prints one screen: the stages, a typical run and where
to read more. `quarry --help-all` prints the full reference: every flag, which flags go with
which stage, the available channels and worked examples. Both are generated from the same
specification the tool validates against, so they can never describe a combination the tool
would reject.

---

## How it works

A Quarry run is five decisions, in order. Only the first two are always required.

| | Decision | Flag |
| :--- | :--- | :--- |
| 1 | Which repository | `--repo <folder-name \| github-url>` (required) |
| 2 | Which stage | `--stage meta\|ledger\|refm\|diff\|ck\|channel\|link\|report` |
| 3 | Which scope | `--full` · `--universe FILE` · `--version TAG` · `--sample FILE` |
| 4 | *(channels only)* Which platform | `--platform git\|github` |
| 5 | *(channels only)* Which channels | `--channel commits\|issues,prs\|all` |

**One stage per run.** There is no combined stage. Each writes its own output and tracks its own
progress, so they run independently and — after `meta` — in any order. A failure in one never
costs you the others.

**Every miner resumes.** Re-run the identical command and it continues from where it stopped:
after an interrupt, a crash, a reboot, or an exhausted API quota. Nothing is mined twice.

**`link` is the exception.** It mines nothing, so re-running it **overwrites** rather than
resumes. See [Linkage](#linkage).

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
| `diff` | Per commit: the message and, per changed file, the removed and added lines | Against the first parent, with no context lines and no rename detection |
| `ck` | Class- and method-level structural metrics per snapshot, via CK | The heaviest stage; pair with `--sample` |
| `channel` | Commits, issues, pull requests, review comments, issue comments | Requires `--platform` and `--channel` |
| `link` | Resolves mined discourse to the commits it refers to | Derives rather than mines; **overwrites** on re-run |
| `report` | Nothing — summarises what the other stages produced | Read-only |

---

## Scope: choosing which commits

`ledger`, `refm`, `diff` and the git commit channel walk history, so they must be told which
commits to walk. There is no default, deliberately.

**`--universe adapter_universe_<project>.json`** — a pinned set of commits: the `head_sha` the
grid was mined from, plus the release commits that never merged back into it. Use this for any
dataset you intend to analyse or publish. It is the only way to guarantee that every stage
walked the same history, which is what makes their outputs joinable. The file comes from a
release-mining step (see [Mining a study](#mining-a-study)) and lives in
`workspace_data/versions/`.

**`--full`** — every commit reachable in the clone. Not frozen: two runs on different days walk
different histories, and the result will not align with anything mined against a pinned
universe. Intended for verification and exploration; the tool prints a warning.

**`--version <tag>`** — check out a single tag or commit and mine only that point.

`ck` is scoped differently. Because it measures snapshots rather than walking commits, it takes
**`--sample rel_hist_<project>.json`** to restrict it to a release grid.

The requirement is strict because the failure it prevents is silent. An unpinned run succeeds,
its records look correct, and they simply never match the ones mined against the grid — no
error, no warning, just a join that quietly loses rows.

### Which commits the Java stages see

`ledger` records every commit in the universe. `refm`, `diff` and the git commit channel list
their commits with `git log <universe> -- '*.java'`, and git simplifies that history by default:
at a merge whose Java files match one parent, it follows only that parent and skips the commits
on the other side. Those commits are in the ledger but have no refactoring, diff or message
record. In the five repos of the study above this was 89 commits, 65 of them in dubbo, such as a
merge of master into a development branch and its revert. Analyses that join the ledger to the
other stages should expect it.

---

## Mining a study

A study needs two things before Quarry runs: the releases to observe and the commits to walk.
Both come from a release-mining step that lists every tag, keeps the general-availability
releases tagged on or before a freeze date, and writes three files per project to
`workspace_data/versions/`:

| File | Holds | Used by |
| :--- | :--- | :--- |
| `rel_hist_<project>.json` | the release grid: each release's tag and commit | `ck --sample`, and the analysis |
| `adapter_universe_<project>.json` | the commit universe: the pinned HEAD and the unmerged release commits | `--universe` |
| `<project>_release_manifest.json` | every tag, and why it was kept or left out | the record of the grid |

Quarry does not make these files: which releases count is a decision of the study, not of the
miner. The release-mining notebook of the refactoring-forecast study is one way to make them
(`release_mining/rel_tag_mining_v4.ipynb` in
[refactoring-forecast-replication](https://github.com/Binamra00/refactoring-forecast-replication)).
It can be adapted to other projects by editing its list of repositories and their tag patterns.

### Making the files for your own projects

Any script can make them, as long as it follows two principles and writes the two formats below.

1. **A frozen grid.** Pick the releases by a rule you can state (for example, every
   general-availability tag dated on or before a freeze date), and record each one's commit.
   Never derive the grid from "today": two runs on different days would give different grids.
2. **A pinned universe.** Record the HEAD commit the grid was taken from, and every release commit
   that HEAD cannot reach (a release on a branch that was never merged back). Quarry walks
   HEAD's history plus those commits, so every stage sees the same commits and every release's
   history is complete.

`adapter_universe_<project>.json`, read by `--universe`:

```json
{
  "repo": "myproject",
  "head_sha": "<the 40-character HEAD commit the grid was taken from>",
  "head_commits": 6229,
  "near_mainline_shas": ["<release commit HEAD cannot reach>", "..."]
}
```

`repo` must match the folder name under `workspace_data/repos/`. `head_commits` (the number of
commits HEAD reaches) is optional; when given, Quarry warns if the clone disagrees.

`rel_hist_<project>.json`, read by `ck --sample` and by an analysis:

```json
{
  "repo": "myproject",
  "head_sha": "<the same HEAD commit>",
  "entries": [
    {"tag": "v1.0.0", "snapshot_sha": "<the release's commit>"},
    {"tag": "v1.1.0", "snapshot_sha": "<the release's commit>"}
  ]
}
```

Put both in `workspace_data/versions/`, then pass their names as shown below. A tag object's id
is accepted where a commit is expected; Quarry resolves it to its commit.

Then mine each project, one stage per run, with `--batch 0` so each stage runs to completion.
These are the stages and the order the study used, for one project:

```bash
P=checkstyle
quarry --repo https://github.com/checkstyle/checkstyle.git --stage meta   # clones it
quarry --repo $P --stage ledger  --universe adapter_universe_$P.json --batch 0
quarry --repo $P --stage refm    --universe adapter_universe_$P.json --batch 0
quarry --repo $P --stage diff    --universe adapter_universe_$P.json --batch 0
quarry --repo $P --stage channel --platform git    --channel commits --universe adapter_universe_$P.json --batch 0
quarry --repo $P --stage channel --platform github --channel all --batch 0
quarry --repo $P --stage link
quarry --repo $P --stage report
```

Any stage can be stopped and run again with the same command; it continues where it stopped.
The GitHub channels take the longest, because of the API's hourly quota.

To repeat the refactoring-forecast study itself, follow Path C of the replication package's
README: it runs its release-mining notebook, then these commands for its five repositories. To
skip the mining entirely, the study's mined files and a git bundle of each repo are on Zenodo
([10.5281/zenodo.24182007](https://doi.org/10.5281/zenodo.24182007)), and the replication
package's notebooks download them.

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

## Linkage

```bash
quarry --repo myproject --stage link
```

Mined discourse is only useful once it reaches code. The `link` stage resolves every issue,
pull request, review comment and issue comment to the commits it refers to, and writes the
result as an edge list.

It mines nothing. It joins files the other stages already wrote, which has one consequence
worth stating plainly:

> **Re-running `link` overwrites its output.** Every other stage appends and resumes, because
> mining is slow and interruptible. Linkage is a whole-corpus join that finishes in seconds and
> is deterministic, so a partial result has no value — and appending would double every edge.
> The files are written to a temporary path and renamed over the target, so an interrupted run
> leaves the previous edge list intact rather than a half-written one.

### One record, many commits

An issue referenced by three commits produces **three links**, not one. Nothing is discarded to
force a single answer, and nothing depends on which route was checked first, so the output is
reproducible by construction.

This makes coverage two different figures, and both are reported:

- **reached** — records with at least one link
- **edges** — the links themselves

One issue with three commits is one reached record and three edges. They will not agree, and
neither is wrong.

### The five routes

| `route` | How the link was found | Strength |
| :--- | :--- | :--- |
| `merge_commit_sha` | The API stated which commit a merged pull request produced | exact |
| `parent_pr_merge` | A review comment's pull request merged | exact |
| `issue_pr_merge` | A pull request body references the issue, and that pull request merged | inferred |
| `commit_message` | A commit message references the number | inferred |
| `parent_number` | A comment inherits the links of the issue or pull request it belongs to | inherited |

`issue_pr_merge` is the route that matters in **squash-merge** projects, where the merge tool
writes the commit message and it frequently references nothing. There the issue reference
survives only in the pull request body, and a strategy that reads commit messages alone badly
undercounts those projects while looking healthy on projects that merge normally.

Each link also records **how** the reference was written: `api` (the platform said so),
`closes` (`Fixes #500`), or `mentions` (a bare `#500`). All three are kept and labelled rather
than merged or filtered, because `Fixes #500` and an offhand `#500` are not the same evidence
and the distinction belongs to whatever consumes the links.

### Links point at the whole repository

A link targets any commit in the clone, as recorded by `meta` — not the pinned study universe.
Membership is carried as columns instead:

| Column | Meaning |
| :--- | :--- |
| `in_ledger` | the commit is in the ledger's universe |
| `in_refm` | RefactoringMiner analysed it |
| `in_ck` | it is a CK snapshot |

Narrowing the evidence to any of those is a filter over the file rather than a different run. A
**blank** flag means that stage has not been run, which is not the same as `0` — the stage ran
and the commit is not in it.

### Output

`links_<project>.csv`, one row per link:

```
source_channel,source_id,resolved_via,target_sha,route,ref_kind,exact,in_ledger,in_refm,in_ck
github.issue,4821,4821,a3f9...,issue_pr_merge,closes,0,1,1,0
```

`source_id` is the `record_id` in the mined channel file, so the text, author and labels are one
join away. They are deliberately **not** copied here: duplicating them would multiply the
dataset and go stale the moment a channel is re-mined.

`linkage_summary_<project>.csv` gives one row per channel — mined, reached, unreached, edges,
the split by reference kind, and how many edges land in each downstream artifact.

`link` requires `meta` to have run, and reads whichever channels are present. It is worth
running after any channel is re-mined.

---

## Output

Results are written to `workspace_data/outputs/`; release-grid definitions live in
`workspace_data/versions/`.

| Artifact | Format | Contents |
| :--- | :--- | :--- |
| `commit_lineage_<project>.jsonl` | JSONL | `meta`: one record per commit in the clone, with all its parents |
| `ledger_history_<project>.jsonl` | JSONL | `ledger`: one record per commit, with its author, time and every Java file it changed (modified, added, deleted or renamed, with the old name) |
| `refactorings_<project>.jsonl` | JSONL | `refm`: one record per commit, with every refactoring RefactoringMiner detected and the files on each side |
| `diffs_<project>.jsonl` | JSONL | `diff`: one record per commit, with its message and, per changed file, the removed and added lines |
| `ck_metrics_<project>.jsonl` | JSONL | `ck`: one record per snapshot: status, timestamp, class and method counts, nested metrics (`ck_sampled_metrics_<project>.jsonl` with `--sample`) |
| `channel_<platform>_<channel>_<project>.jsonl` | JSONL | One record per channel item, in a unified shape across platforms |
| `links_<project>.csv` | CSV | One row per link: which record reaches which commit, by which route |
| `linkage_summary_<project>.csv` | CSV | Per-channel coverage: mined, reached, edges, membership |
| `adapter_universe_<project>.json` | JSON | The pinned commit universe (in `versions/`) |
| `rel_hist_<project>.json` | JSON | The frozen snapshot grid — the release points to be measured (in `versions/`) |
| `<project>_release_manifest.json` | JSON | Every tag, and whether and why it was kept (in `versions/`) |
| `ledger_execution_<project>.log`, `refactorings_<project>.log`, `diffs_<project>.log`, `ck_execution_*_<project>.log` | Text | Per-run diagnostics: failures, timeouts, empty results |

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
| **Strategy** | Channel sources, linkage routes | A source knows how to reach one platform and nothing else; a link producer knows one route to a commit. Adding either adds a class, and nothing else changes. |
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
| CK | 0.7.0, or a build from source | Class- and method-level structural metrics. A jar built from source and placed in `tools/ck/` (`ck-*-SNAPSHOT*-jar-with-dependencies.jar`) is used in preference to the release; its SHA-256 is written on every record. It needs Java 17 or newer. |
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

## Acknowledgements

Quarry runs other people's tools and does not reimplement them. If you publish data mined with it,
please cite the tools its stages used, too.

- **RefactoringMiner** detects the refactorings in the `refm` stage.
  - Tsantalis, N., Ketkar, A. and Dig, D. (2022). RefactoringMiner 2.0. *IEEE Transactions on
    Software Engineering* 48(3), 930–950. https://doi.org/10.1109/TSE.2020.3007722
  - Tsantalis, N., Mansouri, M., Eshkevari, L. M., Mazinanian, D. and Dig, D. (2018). Accurate and
    Efficient Refactoring Detection in Commit History. *ICSE 2018*, 483–494.
    https://doi.org/10.1145/3180155.3180206
- **CK** computes the class and method metrics in the `ck` stage.
  - Aniche, M. (2015). *Java code metrics calculator (CK)*. https://github.com/mauricioaniche/ck
- **Git** walks the history in every stage, and the **GitHub REST API** supplies the issues, pull
  requests, comments and reviews in the `channel` stage.

---

## License and citation

Released under the MIT License.

If you use Quarry in published work, please cite the release archive for the version you used.

Data mined with Quarry:

- Aryal, B. (2026). *Mined Inputs for the Code, Commit History and Issue/PR Discourse Refactoring
  Dataset* (1.0). Zenodo. https://doi.org/10.5281/zenodo.24182007
- Aryal, B. (2026). *Code, Commit History and Issue/PR Discourse for Forecasting Refactoring*
  (2.1). Zenodo. https://doi.org/10.5281/zenodo.24117444