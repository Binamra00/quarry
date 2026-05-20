# Smell-Ranker: Automated Software Repository Mining Engine

**Project:** Automated Code Smell and Refactoring Extraction Pipeline  
**Version:** 1.0.0 (Core Mining Engine)  
**Status:** Stable / Data Acquisition Phase

---

## 1. System Overview

**Smell-Ranker** is an automated, resilient pipeline designed to systematically mine software repositories. It reconstructs the historical evolution of a codebase by extracting objective developer actions (refactorings) and evaluating structural decay (code smells) across the entire Git lineage. 

By automating the orchestration of advanced static analysis tools and version control graph traversal, Smell-Ranker generates the high-fidelity, unified event streams required for downstream machine learning and predictive software engineering research.

### Key Features

#### ⏳ Time-Travel Static Analysis
Unlike traditional tools that only evaluate the *current* state of a repository, Smell-Ranker physically checks out historical commits to snapshot code quality metrics over time, creating a complete evolutionary timeline of architectural technical debt.

#### 📡 Streaming Event Architecture
Scans Git object history and streams detected refactorings and code smells directly to unified append-only logs (`.jsonl`). This prevents the inode exhaustion and memory bloating commonly associated with analyzing large, multi-year repositories.

#### 🛡️ Resilience & Self-Healing
- **Lazarus Protocol:** Automatically tracks execution state commit-by-commit. If a batch job crashes or the host reboots, the pipeline detects the interrupted state, archives corrupt files, and seamlessly resumes from the last valid commit.
- **Poison Pill Defense:** Automatically identifies and quarantines corrupt Git commits or malformed ASTs to prevent infinite retry loops or hanging subprocesses.

---

## 2. File Structure & Organization

### A. Source Code (`smell-ranker/`)

This is the source of truth for all code, strictly adhering to object-oriented design patterns and separation of concerns.

```text
smell-ranker/
├── tests/ # Testing Harness (Pytest Pyramid)
│   ├── conftest.py # Global Fixtures (Mocked Config)
│   ├── unit/ # Layer 1: Logic Verification (BVA)
│   │   ├── batch_state_test.py
│   │   └── metrics_test.py
│   └── integration/ # Layer 2: Mocked Toolchain
│       └── adapters_test.py
│    
├── pipeline/ # The main Python Application Package
│   ├── adapters/ # Tool Adapters Package (Adapter Pattern)
│   │   ├── init.py # Exposes adapters to the main pipeline
│   │   ├── i_adapter.py # Interface for all adapters  
│   │   ├── refm_adapt.py # Wrapper for RefactoringMiner CLI logic
│   │   ├── pmd_adapt.py # Standard PMD Adapter (Snapshot)
│   │   ├── pmd_history_adapt.py # Stateful Adapter for Time-Travel Analysis
│   │   └── metadata_adapt.py # Adapter for extracting Git lineage
│   │
│   ├── bin/ # Executable Shell Scripts (Entry Points)
│   │   └── exec_pipeline.sh # MASTER SCRIPT: Single command to run the experiment
│   │
│   ├── commands/ # CLI Command Templates for adapters (Command Pattern)
│   │   ├── init.py # Exposes command templates to adapters
│   │   ├── i_commands.py # Interface for all command templates 
│   │   └── adapter_cmd.py # CLI commands for external tools like refm and pmd
│   │
│   ├── factories/ # Factory classes to create adapter instances (Factory Pattern)
│   │   ├── init.py # Exposes factories to the main pipeline
│   │   └── adapter_fact.py # Factory to create adapters based on tool name
│   │
│   ├── metrics/ # Metrics classes to generate analysis from adapters output
│   │   ├── init.py # Exposes metrics to the main pipeline
│   │   ├── refm_mets.py # Metrics to analyze refm output (Purity, Signal)
│   │   ├── repo_mets.py # Base metrics for all repos (Churn, Bus Factor)
│   │   ├── pmd_mets.py # Metrics to analyze PMD output (Density, Hotspots)
│   │   └── temp_mets.py # Template Method pattern for reporting lifecycle
│   │
│   ├── rulesets/
│   │   └── pmd_rules_00.xml # PMD Ruleset Configuration
│   │ 
│   ├── utils/ # Python Utility Package
│   │   ├── init.py # Exposes utilities to the app
│   │   ├── adapter_subprocess.py # Subprocess for running shell commands safely
│   │   ├── ui_strategy.py # Universal Console output formatting (Strategy Pattern)
│   │   ├── batch_state.py # Stateful Manager for resumable batch processing
│   │   └── allocate_tools.py # Auto-provisions external tools (PMD/RefM)
│   │
│   ├── main.py # FACADE: Main Python entry point
│   └── config.py # CONFIG: Dynamic path resolution and settings
│ 
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```
## 3. The Execution Pipeline

The pipeline consists of four sequential data-acquisition phases:

| Phase | Component | Responsibility | Output |
| :--- | :--- | :--- | :--- |
| **0** | **Metadata Miner** | Extracts Git Lineage (Parent-Child Graph). | `commit_lineage.jsonl` |
| **1** | **RefactoringMiner** | Extracts historical refactoring operations. | `refactorings.jsonl` |
| **2** | **PMD History** | "Time Travels" to commits to snapshot code quality. | `pmd_history.jsonl` |
| **3** | **Metrics Engine** | Aggregates raw data into density/purity metrics. | `repo_metrics.json` |

The `main.py` facade coordinates the analysis modules sequentially:

### Phase 0: Metadata & Verification
- **Lineage Mining:** `MetadataAdapter` extracts the full Git commit graph (`commit_lineage.jsonl`) to map the evolutionary topology of the repository.
- **Baseline Metrics:** `repo_mets.py` calculates global denominators (Total Commits, Age, Churn) to normalize downstream scores.
- **Dynamic Branch Detection:** Automatically identifies `main` vs. `master` to force the repository into a consistent state before mining.

### Phase 1: History Mining (RefactoringMiner)
- **Scanning:** `RefactoringMinerAdapter` scans the full Git object history to identify architectural changes and developer refactoring intents without requiring physical file checkouts.
- **Resilience:** Uses Explicit File I/O and JSONL streaming to separate data streams from control logs, preventing parser corruption.

### Phase 2: Stateful Candidate Generation (PMD)
- **Time-Travel Strategy:** `PMDHistoryAdapter` physically checks out target commits in history to execute headless static analysis evaluations.
- **Atomic JSONL Streaming:** Results are streamed to a unified `.jsonl` log rather than fragmented XML files.
- **Crash Recovery:** The `BatchStateManager` persists progress atomically, allowing the execution pipeline to resume exactly where it left off in the event of an interruption.

### Phase 3: Metrics Aggregation
- **Consolidation:** `pmd_mets.py` and `refm_mets.py` read the raw event streams to calculate high-level structural indicators like "Smell Density" and "Refactoring Purity".
- **Normalization:** Converts raw pipeline counts into standardized, comparable metrics (e.g., Smells per KLOC) for cross-project evaluation.

---

## 4. Key Data Artifacts

All results are routed to the dynamically configured `workspace_data/outputs` directory.

### 📂 Generated Artifacts

| Artifact | Format | Description |
|--------|--------|-------------|
| **`commit_lineage_[repo].jsonl`** | **JSONL** | Git Commit Graph (Parent-Child relationships). |
| `repo_metrics_[repo].json` | JSON | Project metadata (Age, Churn, Languages). |
| `refactorings_[repo].jsonl` | JSONL | Stream of all refactoring operations detected in history. |
| `pmd_history_[repo].jsonl` | JSONL | Unified Event Stream containing structural rule violations. |
| `pmd_metrics_[repo].json` | JSON | Aggregated density and structural hotspot analysis. |
| `batch_status_[tool]_[repo].json` | JSON | State File. Tracks the last successfully processed commit index for the "Lazarus" resume capability. |
| `*_execution_[repo].log` | Text | Diagnostic Log. Records critical failures (checkouts, crashes, timeouts). |

---

## 5. Local Installation & Usage (Windows / Linux / macOS)

The system is strictly OS-Agnostic and automatically detects Windows (`.bat`) vs Unix (`.sh`) tool binaries.

### Prerequisites
- **Python 3.10+**
- **Java 21** (Required for PMD 7.x). Verify with `java -version`.
- **Git** installed and accessible in the system `PATH`.

### 1. Clone the Repository
```bash
git clone [https://github.com/Binamra00/smell-ranker.git](https://github.com/Binamra00/smell-ranker.git)
cd smell-ranker
```

### 2. Setup Python Environment
```bash
# 1. Create the venv
python -m venv venv

# 2. Allow script execution (Windows only, if blocked)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# 3. Activate:
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

# 4. Install dependencies
pip install -r requirements.txt
```

### 3. Provision Analysis Tools
You must manually trigger the tool downloader once. This script fetches the correct versions of PMD and RefactoringMiner and configures executable permissions automatically.
```bash
python -m pipeline.utils.allocate_tools
```
*A new `workspace_data` folder will be generated in your project root to sandbox all operations.*

### 4. Repository Setup
The pipeline includes a smart `RepositoryLoader` that handles acquisition automatically. 
- **URL Mode (Auto-Clone):** Pass a GitHub URL. The system will automatically clone it into `workspace_data/repos/`.
- **Local Mode:** Pass a folder name if the repository already exists in `workspace_data/repos/`.

### 5. Run the Pipeline
Execute the orchestrator using the main facade.
```bash
python -m pipeline.main --repo <URL_OR_NAME> --stage <STAGE> [OPTIONS]
```
**Available Stages:** `all`, `meta`, `refm`, `pmd`, `pmd_history`

---

## 6. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices.

| Principle | Implementation |
|---------|----------------|
| **Idempotency** | `BatchStateManager` allows the pipeline to resume safely after crashes without data duplication. |
| **Separation of Concerns** | Logic `pipeline/`, config `config.py`, and adapters `pipeline/adapters/` are strictly distinct and decoupled. |
| **Command Pattern** | `main.py` (Invoker) executes encapsulated `RunToolCommand` objects, treating all mining tools interchangeably. |
| **Adapter Pattern** | `IAdapter` interface standardizes the execution of diverse external CLI tools (PMD, RefactoringMiner, Git). |
| **Factory Method** | `ToolFactory` encapsulates adapter instantiation logic, keeping the orchestrator clean. |
| **Template Method** | `BaseMetrics` defines the skeleton algorithm for generating end-of-run diagnostic reports. |
| **Strategy Pattern** | `ui_strategy.py` allows universal and dynamic console output formatting. |
| **Pipe and Filter** | Independent mining adapters generate distinct data streams designed for downstream fusion. |

---

## 7. Toolchain Configuration

### RefactoringMiner
- **Version**: 3.0.12
- **Build Requirement**: Java 17+
- **Role**: Phase 1 – History & Intent Mining

### PMD
- **Version**: 7.19.0
- **Role**: Phase 2 – Structural Decay & Code Smell Detection
- **Configured Ruleset**: `pmd_rules_00.xml`

---

## 8. Verification & QA (The "Zero-Touch" Pipeline)

The reliability of Smell-Ranker is guaranteed by a **3-Layer Testing Pyramid**. 

### Layer 1: Logic Verification (Unit)
- **Math Safety**: Validates that density/purity formulas handle mathematical edge cases (e.g., `total_commits=0`) without crashing (Boundary Value Analysis).
- **State Resilience**: Verifies the "Lazarus Protocol" — ensuring the system correctly identifies corrupt state files, archives them, and self-heals without user intervention.
- **Idempotency**: Proves that processing the same commit multiple times does not append duplicate JSONL records or skew aggregation metrics.

### Layer 2: Tool Orchestration (Integration)
- **Poison Pill Defense**: Verifies that if an external tool (PMD) hangs indefinitely on a complex AST, the pipeline catches the subprocess timeout, logs the failure, and continues mining.
- **Exit Code Semantics**: Confirms that PMD `Exit Code 4` is correctly mapped to "Violations Found" (Success), preventing false-positive system failures.

### Layer 3: Environment Safety Nets
- **State Reversion**: Verifies that the repository working tree always reverts to the target default branch (`main` / `master`) even if the Python process is abruptly terminated mid-checkout.

**Run the suite locally:**
```bash
pytest tests/ -v
# Run only unit tests
pytest tests/unit/
```