# Smell-Ranker: Infrastructure & Architecture Documentation

**Project:** Automated Code Smell Prioritization and Ranking  
**Version:** 0.8 (Phase 3.4 – DevOps & Automation)

---

## 1. System Overview

**Smell-Ranker** is an automated pipeline designed to generate a **“Fortified Ground Truth”** for code smell prioritization. It achieves this by mining software repositories to extract objective developer actions (refactoring, bug-fixing) and using them to score code smells detected by static analysis.

The system operates on a **Universal Hybrid Workflow** that leverages three distinct environments to ensure persistence, scalability, and reproducibility.

### The Hybrid Workflow

The architecture splits responsibilities across three layers:

- **Persistent Storage (Google Drive / Local Disk):** Holds the “state” of the project (tools, input data, results).
- **Development Environment (Local/GitHub):** Where the logic is written and versioned.
- **Runtime Environment (Google Colab / Docker / Local):** A compute engine that executes the logic. The pipeline automatically detects its environment and adapts filesystem paths accordingly.

---

## 2. File Structure & Organization

### A. Source Code (`smell-ranker/`)

This is the source of truth for all code. It is version-controlled on GitHub.

```commandline
smell-ranker/
├── .github/ # CI/CD Automation
│   ├── workflows/
│   │   ├── ci_tests.yml # The Verifier (Runs Pytest)
│   │   └── dev_delivery.yml # The Logistics Manager (Auto-Merge)
│   └── CODEOWNERS # Defines @copilot as the required reviewer
│
├── tests/ # Testing Harness (Pytest Pyramid)
│   ├── conftest.py # Global Fixtures (Mocked Config)
│   ├── unit/ # Layer 1: Logic Verification (BVA)
│   │   ├── batch_state_test.py
│   │   └── metrics_test.py
│   └── integration/ # Layer 2: Mocked Toolchain
│       └── adapters_test.py
│    
├── pipeline/ # The main Python Application Package
│ ├── adapters/ # Tool Adapters Package (Adapter Pattern)
│ │ ├── init.py # Exposes adapters to the main pipeline
│ │ ├── i_adapter.py # Interface for all adapters  
│ │ ├── refm_adapt.py # Wrapper for RefactoringMiner CLI logic
│ │ ├── pmd_adapt.py # Standard PMD Adapter (Snapshot)
│ │ └── pmd_history_adapt.py # Stateful Adapter for Time-Travel Analysis
│ │
│ ├── bin/ # Executable Shell Scripts (Entry Points)
│ │ ├── exec_pipeline.sh # MASTER SCRIPT: Single command to run the experiment
│ │ └── colab_git_setup...# SYNC SCRIPT: Secure Git cloning/pulling in Colab
│ │
│ │── commands/ # CLI Command Templates for adapters (Command Pattern)
│ │ ├── init.py # Exposes command templates to adapters
│ │ ├── i_commands.py # Interface for all command templates 
│ │ └── adapter_cmd.py # CLI commands for external tools like refm and pmd
│ │
│ │── factories/ # Factory classes to create adapter instances (Factory Pattern)
│ │ ├── init.py # Exposes factories to the main pipeline
│ │ └── adapter_fact.py # Factory to create adapters based on tool name
│ │
│ ├── metrics/ # Metrics classes to generate analysis from adapters output
│ │ ├── init.py # Exposes metrics to the main pipeline
│ │ ├── refm_mets.py # Metrics to analyze refm output (Purity, Signal)
│ │ ├── repo_mets.py # Base metrics for all repos (Churn, Bus Factor)
│ │ ├── pmd_mets.py # Metrics to analyze PMD output (Density, Hotspots)
│ │ └── temp_mets.py # Template Method pattern for reporting lifecycle
│ │
│ │── rulesets/
│ │ └── pmd_rules_00.xml # PMD Ruleset Configuration
│ │ 
│ ├── utils/ # Python Utility Package
│ │ ├── init.py # Exposes utilities to the app
│ │ ├── adapter_subprocess.py # Subprocess for running shell commands safely
│ │ ├── ui_strategy.py # Universal Console output formatting (Strategy Pattern)
│ │ ├── batch_state.py # Stateful Manager for resumable batch processing
│ │ └── allocate_tools.py # Auto-provisions external tools (PMD/RefM)
│ │
│ ├── main.py # FACADE: Main Python entry point
│ ├── heuristic_seeds.json # Heuristic Thresholds to guide metric analysis
│ └── config.py # CONFIG: Dynamic path resolution and settings
│ 
└── docs/ # Project Documentation
│   └── Master Thesis Log.pdf
└── .env
└── .gitignore
└── requirements.txt
└── README.md
```
## 3. The Execution Pipeline

The `main.py` facade coordinates the analysis modules sequentially:

### Phase 0: Verification & Baseline
- **Dynamic Branch Detection:** Automatically identifies `main` vs. `master` to force the repository into a consistent state.
- **Repo Mining:** `repo_mets.py` calculates the global denominator (Total Commits) and baseline heuristics.

### Phase 1: History Mining (RefactoringMiner)
- **Scanning:** `RefactoringMinerAdapter` scans the full Git object history to identify architectural changes without requiring physical file checkouts.
- **Resilience:** Uses Explicit File I/O to separate data streams from control logs, preventing parser corruption.

### Phase 2: Stateful Candidate Generation (PMD)
- **Time-Travel Strategy:** `PMDHistoryAdapter` physically checks out each commit in history to run static analysis.
- **Atomic JSONL Streaming:** Results are streamed to a unified `.jsonl` log (JSON Lines) rather than fragmented files, solving inode exhaustion risks.
- **Poison Pill Defense:** Automatically identifies and quarantines corrupt Git commits to prevent infinite retry loops.
- **Crash Recovery:** The `BatchStateManager` persists progress atomically. If the process is killed (e.g., Colab timeout), it resumes exactly where it left off ("Lazarus" capability).

## 4. Key Data Artifacts

All results are stored in the `persistent_storage` path (e.g., Google Drive).

| Artifact | Format | Description |
|--------|--------|-------------|
| `repo_metrics_[repo].json` | JSON | Project metadata (Age, Churn, Languages). |
| `refactorings_[repo].json` | JSON | List of all refactoring operations detected in history. |
| `pmd_history_[repo].jsonl` | JSONL | Unified Event Stream. Contains every PMD run (Success/Failure/Violations) in a single, append-only log file. |
| `pmd_metrics_[repo].json` | JSON | Aggregated density and hotspot analysis. |
| `batch_status_[tool]_[repo].json` | JSON | State File. Tracks the last successfully processed commit index for resume capability. |
| `*_execution_[repo].log` | Text | Diagnostic Log. Records only critical failures (checkouts, crashes, timeouts). |


## 5. Execution Flow (The “How-To”)

The system is designed to be run from **Google Colab** or a **local machine**.

---

### Step 1: Initialization

**Trigger**
- User runs:
  - `!bash exec_pipeline.sh` (Colab)  
  - `python -m pipeline.main` (Local)

**Action**
- The system detects the environment.
  - **Colab**: Mounts Google Drive
  - **Local**: Creates a `workspace_data/` directory

**Result**
- Tools (PMD, RefactoringMiner) are downloaded and provisioned automatically
- Target repositories are cloned if missing

---

### Step 2: Analysis Phases

The pipeline executes the following stages sequentially or individually via flags.

---

#### Phase 0: Metric Verification

- **Module**: `repo_metrics.py`
- **Action**: Mines the total commit history to calculate project stats (LOC, Churn, Age)
- **Output**:  
  - `repo_metrics_[repo_name].json`  
  - Includes Churn Map

---

#### Phase 1: History Mining

- **Module**: `refm_adapt.py`
- **Strategy**: Forced-Loop  
  Iterates explicitly through `git rev-list` to capture all commits (including detached heads) while filtering out non-code noise.
- **Optimization**: Smart Skipping to bypass already processed commits
- **Output**:  
  - `refactorings_[repo_name].json`

---

#### Phase 2: Stateful Candidate Generation

- **Module**: `pmd_history_adapt.py`
- **Strategy**: Time-Travel Batching
- **Stateful**: Uses `BatchStateManager` to track progress commit-by-commit  
  - Resumes instantly after crashes
- **Buffered**: Lazy Flushing to minimize disk I/O
- **Silent Mode**:  
  - Redirects verbose logs to `pmd_history_execution.log` to keep the console clean
- **Output**:  
  - `outputs/pmd_raw/[repo_name]/pmd_out_[sha].json` (thousands of files)

---

#### Phase 3: Aggregation & Metrics

- **Module**: `pmd_mets.py`
- **Action**: Aggregates fragmented batch files into a unified dataset
- **Metrics**:
  - Smell Density
  - Intensity
  - Hotspots
- **Output**:  
  - `pmd_metrics_[repo_name].json`

---

## 6. 🚀 Local Installation & Usage

You can run **Smell-Ranker** on your local machine (Windows / Linux / macOS).  
The system is fully self-contained.

---

### Prerequisites

- Python 3.10+
- Java 21 (required for PMD 7.x)
- Git installed and accessible in `PATH`

---

### 1. Clone the Repository

```bash
git clone https://github.com/Binamra00/smell-ranker.git
cd smell-ranker
```
### 2. Setup Python Environment

It is recommended to use a virtual environment.

```bash
python3 -m venv venv

# Activate:
# Linux/Mac: source venv/bin/activate
# Windows:   venv\Scripts\activate

pip install -r requirements.txt
```
### 3. Prepare Your Target Repository

The pipeline analyzes repositories located in `smell-ranker/workspace_data/repos/`. You must set this up manually before running the analysis.

**Step A: Initialize the Workspace** Run the pipeline's help command. This triggers the configuration script, which automatically creates the required `workspace_data` folder structure inside the project.

```bash
# Ensure you are in the 'smell-ranker' root directory
python -m pipeline.main --help
```
You should now see a new folder named `workspace_data` in your project root.

**Step B: Clone Your Target**

Navigate into the newly created `repos` folder and clone the project you want to analyze.

```bash
cd workspace_data/repos

# Example: Clone Apache Commons Lang
git clone https://github.com/apache/commons-lang.git
```

**Step C: Return to Root**

Go back to the main `smell-ranker` directory to run the pipeline:

```bash
cd ../..
```

## 7. Run the Pipeline

You can now analyze the repository you just cloned.

```bash
# General Syntax
# --repo must match the folder name inside workspace_data/repos/
python3 -m pipeline.main --repo commons-lang --stage all --batch-size 50
```
### Tools
- PMD and RefactoringMiner are downloaded automatically to:  
  `workspace_data/tools` (on first run)

### Results
- Output JSON files appear in:  
  `workspace_data/outputs`

### Logs
- Execution logs are saved to:  
  `workspace_data/outputs/pmd_history_execution_[repo].log`

---

## 8. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices.

| Principle | Implementation                                                                                        |
|---------|-------------------------------------------------------------------------------------------------------|
| Continuous Integration | `ci_tests.yml` enforces "Shift-Left" verification on every push                                       |
| Continuous Delivery | `auto_merge.yml` automates PR creation, review, and merging                                           |
| Idempotency | `BatchStateManager` allows the pipeline to resume safely after crashes                                        |
| Separation of Concerns | Logic `pipeline/`, configuration `config.py`, and adapters `pipeline/adapters/` are strictly distinct |
| Command Pattern | `main.py` (Invoker) executes encapsulated `RunToolCommand` objects                                    |
| Adapter Pattern | `IAdapter` interface standardizes diverse tools (PMD, RefactoringMiner)                               |
| Factory Method | `ToolFactory` encapsulates adapter instantiation logic                                                |
| Template Method | `BaseMetrics` defines the skeleton algorithm for metric reporting                                     |
| Strategy Pattern | `ui_strategy.py` selects visualization (Jupyter Widget vs. standard `\r`)                             |
| Fail-Fast | Critical dependencies (e.g., PyDriller) are checked at startup                                        |

---

## 9. Toolchain Configuration

### RefactoringMiner
- **Version**: 3.0.12
- **Build Requirement**: Java 17+
- **Role**: Pass 1 – History mining

### PMD
- **Version**: 7.19.0
- **Role**: Pass 2 – Candidate generation
- **Detected Smells**:
  - God Class
  - Long Method
  - Feature Envy
  - Cyclomatic Complexity

---

## 10. Verification & QA (The "Zero-Touch" Pipeline)

The reliability of Smell-Ranker is guaranteed by a **3-Layer Testing Pyramid** that runs automatically on every push to `dev`. We currently maintain a **100% Pass Rate** across 17 distinct test scenarios.

### Layer 1: Logic Verification (Unit)
- **Math Safety**: Validates that density/purity formulas handle edge cases (e.g., `total_commits=0`) without crashing (BVA).
- **State Resilience**: Verified the "Lazarus Protocol" — the system correctly identifies corrupt state files, archives them, and self-heals.
- **Idempotency**: Proven that processing the same commit multiple times does not skew metrics.

### Layer 2: Tool Orchestration (Integration)
- **Poison Pill Defense**: Verified that if an external tool (PMD) hangs, the pipeline catches the timeout, logs it, and continues.
- **Exit Code Semantics**: Confirmed that PMD `Exit Code 4` is correctly interpreted as "Violations Found" (Success), not a system failure.

### Layer 3: Safety Nets
- **Time-Travel Safety**: Verified that the repository always reverts to `main` even if the analysis process crashes mid-operation.

**Run the suite locally:**
```bash
pytest tests/ -v
# Run only unit tests
pytest tests/unit/
```

## 11. Future Roadmap

- [x] **Phase 3: Scalability & Resilience** (Completed Dec 2025)
  - [x] JSONL Streaming for inode optimization
  - [x] "Lazarus" Crash Recovery
  - [x] DevOps Pipeline (CI/CD)
- [ ] **Phase 4: Heuristic Correlator** - Implement `overlap_score.py` to link Refactoring events to Smells.
  - Development of `Heuristic B` (AST-Proximity).
- [ ] **Phase 5: Oracle Project Execution** - Full-scale run on `apache/commons-lang`.
