# Smell-Ranker: Automated Code Smell Prioritization and Ranking

**Project:** Automated Code Smell Prioritization and Ranking  
**Version:** 1.0.0 (Operational Pipeline)  
**Status:** Phase 4.2 Complexity Analysis (Next Up)

---

## 1. System Overview

**Smell-Ranker** is an automated pipeline designed to generate a **“Fortified Ground Truth”** for code smell prioritization. It achieves this by mining software repositories to extract objective developer actions (refactoring, bug-fixing) and using them to score code smells detected by static analysis.

The system features a novel **Causality-Aware Heuristic Engine** that uses "Time Travel" (Commit Lineage Mining) to distinguish between refactorings that *fixed* a smell versus those that merely co-occurred with it.

### Key Features

#### 🧠 Causality-Aware Analysis
Unlike traditional tools that only look at the *current* state, Smell-Ranker reconstructs the commit history graph to perform **Pre-Condition Checks**.
- **Fixed Smells:** Detected when a smell existed in the *Parent Commit* but vanished in the *Current Commit* (Strong Causality).
- **Persistent Smells:** Detected when a smell survived the refactoring (Weak Causality).

#### ⚡ "Out-of-Core" Performance
Built on the **Polars** DataFrame library, the Heuristic Engine processes GB-scale datasets in milliseconds using a streaming, lazy-evaluation architecture.

#### 🛡️ Resilience & Self-Healing
- **Lazarus Protocol:** Automatically detects crashed batch jobs and resumes from the last valid checkpoint.
- **Poison Pill Defense:** Isolates and skips specific commits that cause external tools (PMD) to hang.

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
│ ├── heuristics/                  # NEW PACKAGE: The Correlator Service
│ │ ├── __init__.py              # Exposes HeuristicEngine to main.py
│ │ ├── interface.py             # THE CONTRACT: Defines 'IHeuristicStrategy'
│ │ ├── engine.py                # THE ORCHESTRATOR: Polars pipeline manager
│ │ ├── loader.py                # THE DAL: Schema definitions & Lazy Loading
│ │ ├── factory.py               # THE CREATOR: Instantiates strategies dynamically
│ │ └── strategies/              # THE LOGIC: Where specific heuristics live
│ │     ├── __init__.py
│ │     ├── ast_proximity.py     # Heuristic B (Implementation)
│ │     ├── complexity.py        # Heuristic A (Placeholder for future)
│ │     └── criticality.py       # Heuristic C (Placeholder for future) 
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

The pipeline consists of four sequential phases:

| Phase | Component | Responsibility | Output |
| :--- | :--- | :--- | :--- |
| **0** | **Metadata Miner** | Extracts Git Lineage (Parent-Child Graph) for Time Travel. | `commit_lineage.jsonl` |
| **1** | **RefactoringMiner** | Extracts historical refactoring operations. | `refactorings.jsonl` |
| **2** | **PMD History** | "Time Travels" to every commit to snapshot code quality. | `pmd_history.jsonl` |
| **3** | **Metrics Engine** | Aggregates raw data into density/purity metrics. | `repo_metrics.json` |
| **4** | **Heuristic Engine** | Correlates all inputs to prove causality. | `ground_truth.parquet` |

The `main.py` facade coordinates the analysis modules sequentially:

### Phase 0: Metadata & Verification
- **Lineage Mining:** `MetadataAdapter` extracts the full Git commit graph (`commit_lineage.jsonl`) to build a "Time Machine" map for the Heuristic Engine.
- **Baseline Metrics:** `repo_mets.py` calculates global denominators (Total Commits, Age, Churn) to normalize downstream scores.
- **Dynamic Branch Detection:** Automatically identifies `main` vs. `master` to force the repository into a consistent state.

### Phase 1: History Mining (RefactoringMiner)
- **Scanning:** `RefactoringMinerAdapter` scans the full Git object history to identify architectural changes without requiring physical file checkouts.
- **Resilience:** Uses Explicit File I/O and JSONL streaming to separate data streams from control logs, preventing parser corruption.

### Phase 2: Stateful Candidate Generation (PMD)
- **Time-Travel Strategy:** `PMDHistoryAdapter` physically checks out each commit in history to run static analysis.
- **Atomic JSONL Streaming:** Results are streamed to a unified `.jsonl` log rather than fragmented files, solving inode exhaustion risks.
- **Poison Pill Defense:** Automatically identifies and quarantines corrupt Git commits to prevent infinite retry loops.
- **Crash Recovery:** The `BatchStateManager` persists progress atomically ("Lazarus" capability), allowing execution to resume exactly where it left off.

### Phase 3: Metrics Aggregation
- **Consolidation:** `pmd_mets.py` and `refm_mets.py` read the raw event streams to calculate high-level indicators like "Smell Density" and "Refactoring Purity".
- **Normalization:** Converts raw counts into comparable metrics (e.g., Smells per KLOC) for cross-project analysis.

### Phase 4: Heuristic Correlation (Causality Engine)
- **Polars Streaming Engine:** `HeuristicEngine` uses an "Out-of-Core" architecture to join GB-scale datasets (Refactorings + Smells) in milliseconds.
- **Dual-Lookup Algorithm:** The `AST_Proximity` strategy uses the Phase 0 Lineage map to check the **Pre-Condition** (Parent Commit) and **Post-Condition** (Current Commit) of every refactoring.
- **Causality Classification:** Distinguishes between **Fixed Smells** (Strong Causality) and **Persistent Smells** (Weak Causality).

## 4. Key Data Artifacts

All results are stored in the `persistent_storage` path (e.g., Google Drive).

### 📂 Generated Artifacts

| Artifact | Format | Description |
|--------|--------|-------------|
| **`commit_lineage_[repo].jsonl`** | **JSONL** | **Phase 0 Output.** Git Commit Graph (Parent-Child relationships) required for "Time Travel" lookups. |
| `repo_metrics_[repo].json` | JSON | Project metadata (Age, Churn, Languages). |
| `refactorings_[repo].jsonl` | JSONL | Stream of all refactoring operations detected in history. |
| `pmd_history_[repo].jsonl` | JSONL | Unified Event Stream. Contains every PMD run (Violations) in a single, append-only log file. |
| **`ground_truth_[repo].parquet`** | **Parquet** | **Phase 4 Output.** The Final Dataset. Contains joined Refactoring-Smell pairs with `Fixed` vs `Persistent` causality scores. |
| `pmd_metrics_[repo].json` | JSON | Aggregated density and hotspot analysis. |
| `batch_status_[tool]_[repo].json` | JSON | State File. Tracks the last successfully processed commit index for the "Lazarus" resume capability. |
| `*_execution_[repo].log` | Text | Diagnostic Log. Records only critical failures (checkouts, crashes, timeouts). |


## 6. Execution Flow (The “How-To”)

The system is designed to be run as a **CLI Application** on a local machine or server.

---

### Step 1: Initialization

**Trigger**
- User runs: `python -m pipeline.main --repo [url] --stage all`

**Action**
- The system automatically detects the OS and creates a `workspace_data/` directory.
- **Lazy Provisioning:** Checks for tools (PMD, RefactoringMiner). If missing, downloads and configures them JIT (Just-In-Time).

---

### Step 2: Analysis Phases

The pipeline executes the following stages sequentially.

#### Phase 0: Metadata & Verification
- **Module:** `metadata_adapt.py` & `repo_mets.py`
- **Action:** 1. Mines the full commit lineage ($Child \to Parent$) for "Time Travel" lookups.
  2. Calculates global denominators (Age, Churn, Total Commits).
- **Output:** - `commit_lineage_[repo].jsonl` (Lineage Map)
  - `repo_metrics_[repo].json` (Baseline Stats)

---

#### Phase 1: History Mining (RefactoringMiner)
- **Module:** `refm_adapt.py`
- **Strategy:** **Streaming IO**
  - Scans the Git object history without physical checkout.
  - Streams detected refactorings directly to a unified log.
- **Output:** - `refactorings_[repo].jsonl` (Append-Only Stream)

---

#### Phase 2: Stateful Candidate Generation (PMD)
- **Module:** `pmd_history_adapt.py`
- **Strategy:** **Time-Travel Batching**
  - Physically checks out every commit to run static analysis.
  - Uses `BatchStateManager` to track progress commit-by-commit ("Lazarus Protocol").
- **Optimization:** - Writes to a **Unified Event Stream** (`.jsonl`) instead of creating thousands of small files, preventing inode exhaustion.
- **Output:** - `pmd_history_[repo].jsonl` (Unified Stream)

---

#### Phase 3: Metrics Aggregation
- **Module:** `pmd_mets.py`
- **Action:** Reads the raw history stream to calculate density and purity metrics.
- **Output:** - `pmd_metrics_[repo].json`

---

#### Phase 4: Heuristic Causality Engine
- **Module:** `heuristic_cmd.py` -> `polars_engine.py`
- **Strategy:** **Out-of-Core Correlation**
  - Joins the Refactoring Stream, PMD Stream, and Lineage Map.
  - Executes the **Dual-Lookup Algorithm** to detect if a smell was *Fixed* or *Persistent*.
- **Output:** - `ground_truth_[repo].parquet` (High-Performance Dataset)

## 6. 🚀 Local Installation & Usage (Windows / Linux / macOS)

You can run **Smell-Ranker** natively on your local machine. The system is now **OS-Agnostic** and automatically detects Windows (`.bat`) vs Linux (`.sh`) tool binaries.

### Prerequisites

- **Python 3.10+**
- **Java 21** (Required for PMD 7.x). Verify with `java -version`.
- **Git** installed and accessible in `PATH`.

---

### 1. Clone the Repository

```bash
git clone https://github.com/Binamra00/smell-ranker.git
cd smell-ranker
```
### 2. Setup Python Environment

It is recommended to use a virtual environment to isolate dependencies.

```bash
# 1. Create the venv
python -m venv venv

# 2. Allow script execution (if blocked)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# 3. Activate:
# Linux/Mac: 
source venv/bin/activate
# Windows:   
.\venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt
```
### 3. Provision Analysis Tools

Unlike the Cloud/Colab environment, you must manually trigger the tool downloader once. This script fetches PMD and RefactoringMiner and configures executable permissions automatically.

```bash
# Ensure you are in the 'smell-ranker' root directory
python -m pipeline.utils.allocate_tools
```
You should now see a new folder named `workspace_data` in your project root.

### 4. Repository Setup

The pipeline includes a smart `RepositoryLoader` that handles acquisition automatically. You generally **do not** need to manually clone repositories.

**Modes of Operation:**
1.  **URL Mode (Auto-Clone):** Pass a GitHub URL (e.g., `https://github.com/user/repo.git`). The system will automatically clone it into `workspace_data/repos/`.
2.  **Local Mode:** Pass a folder name (e.g., `toy_project`) if the repository already exists in `workspace_data/repos/`.

**Workspace Initialization:**
The `workspace_data` directory structure (inputs/outputs/tools) is automatically created and provisioned the first time you run the pipeline.

---

### 5. Run the Pipeline

You are now ready to execute the analysis. The system automatically detects your OS and uses the appropriate tool binaries.

**Command Syntax:**
```bash
python -m pipeline.main --repo <URL_OR_NAME> --stage <STAGE> [OPTIONS]
```

## 8. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices.

| Principle | Implementation |
|---------|----------------|
| **Continuous Integration** | `ci_tests.yml` enforces "Shift-Left" verification on every push. |
| **Continuous Delivery** | `auto_merge.yml` automates PR creation, review, and merging. |
| **Idempotency** | `BatchStateManager` allows the pipeline to resume safely after crashes. |
| **Separation of Concerns** | Logic `pipeline/`, config `config.py`, and adapters `pipeline/adapters/` are strictly distinct. |
| **Command Pattern** | `main.py` (Invoker) executes encapsulated `RunToolCommand` objects. |
| **Adapter Pattern** | `IAdapter` interface standardizes diverse tools (PMD, RefactoringMiner, Git Log). |
| **Factory Method** | `ToolFactory` and `HeuristicFactory` encapsulate object instantiation logic. |
| **Template Method** | `BaseMetrics` defines the skeleton algorithm for metric reporting. |
| **Strategy Pattern** | `ui_strategy.py` (UI) and `IHeuristicStrategy` (Logic) allow runtime algorithm swapping. |
| **Chain of Responsibility** | `HeuristicEngine` executes a dynamic sequence of strategies (e.g., AST $\to$ Complexity $\to$ Criticality). |
| **Pipe and Filter** | `MetadataAdapter` produces lineage data which is consumed downstream by the Heuristic Engine. |
| **Lazy Evaluation** | `polars_engine.py` uses execution graphs to process GB-scale datasets without loading them into RAM. |

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

- [x] **Phase 1: History Mining** (Completed)
- [x] **Phase 2: Static Analysis Integration** (Completed)
- [x] **Phase 3: Resilience & Scalability** (Completed)
- [ ] **Phase 4: Multi-Dimensional Heuristics** (In Progress)
  - [x] **Phase 4.1: Causality Core (Time Travel)** (Completed Jan 2026)
    - [x] Metadata Lineage Extraction
    - [x] AST Proximity Strategy (Fix Detection)
    - [x] Polars Streaming Engine
  - [ ] **Phase 4.2: Complexity Analysis** (Next Up)
    - [ ] `ComplexityStrategy`: Calculate Cyclomatic Complexity Delta ($\Delta CC$).
    - [ ] Correlate refactoring effort with complexity reduction.
  - [ ] **Phase 4.3: Criticality & Churn**
    - [ ] `CriticalityStrategy`: Integrate "Bus Factor" and "File Churn".
    - [ ] Prioritize smells in frequently touched/high-risk files.
- [ ] **Phase 5: Large Scale Validation** (Future)
  - [ ] Analysis of `commons-io` (Medium Scale)
  - [ ] Analysis of `junit4` (High Scale)
  - [ ] Final Thesis Data Visualization
