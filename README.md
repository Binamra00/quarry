# Smell-Ranker: Infrastructure & Architecture Documentation

**Project:** Automated Code Smell Prioritization and Ranking  
**Version:** 0.6 (Phase 3.2 – Stateful & Universal Pipeline)

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
│ │ ├── cmd_subprocess.py # Subprocess for running shell commands safely
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
## 3. Execution Flow (The “How-To”)

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

## 4. 🚀 Local Installation & Usage

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
## 2. Setup Python Environment

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

## 4. Run the Pipeline

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

## 5. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices.

| Principle | Implementation |
|---------|----------------|
| Separation of Concerns | Logic (`pipeline/`), configuration (`config.py`), and adapters (`pipeline/adapters/`) are strictly distinct |
| Command Pattern | `main.py` (Invoker) executes encapsulated `RunToolCommand` objects |
| Adapter Pattern | `IAdapter` interface standardizes diverse tools (PMD, RefactoringMiner) |
| Factory Method | `ToolFactory` encapsulates adapter instantiation logic |
| Template Method | `BaseMetrics` defines the skeleton algorithm for metric reporting |
| Strategy Pattern | `ui_strategy.py` selects visualization (Jupyter Widget vs. standard `\r`) |
| Fail-Fast | Critical dependencies (e.g., PyDriller) are checked at startup |

---

## 6. Toolchain Configuration

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

## 7. Future Roadmap

- **Phase 4: Oracle Project Execution**  
  Run the pipeline on `commons-lang` or `junit`

- **Phase 5: Heuristic Correlator**  
  Implement `overlap_score.py` to link Refactoring events (Pass 1) to PMD violations (Pass 2)
