# Smell-Ranker: Infrastructure & Architecture Documentation

**Project:** Automated Code Smell Prioritization and Ranking  
**Version:** 0.3 (Phase 1 – Smoke Test Complete)

---

## 1. System Overview

**Smell-Ranker** is an automated pipeline designed to generate a **“Fortified Ground Truth”** for code smell prioritization. It achieves this by mining software repositories to extract objective developer actions (refactoring, bug-fixing) and using them to score code smells detected by static analysis.

The system operates on a **Hybrid Workflow** that leverages three distinct environments to ensure persistence, scalability, and reproducibility.

### The Hybrid Workflow

The architecture splits responsibilities across three layers:

- **Persistent Storage (Google Drive):** Holds the “state” of the project (tools, input data, results).
- **Development Environment (Local/GitHub):** Where the logic is written and versioned.
- **Runtime Environment (Google Colab):** A disposable compute engine that executes the logic.

---

## 2. File Structure & Organization

### A. Local Development (`smell-ranker/`)

This is the source of truth for all code. It is version-controlled on GitHub.

```commandline
smell-ranker/
├── pipeline/ # The main Python Application Package
│ ├── adapters/ # [NEW] Tool Adapters Package (Structural Pattern)
│ │ ├── refm_adapt.py # Wrapper for RefactoringMiner CLI logic
│ │ ├── pmd_adapt.py # Wrapper for PMD CLI logic
│ │ └── init.py # Exposes adapters to the main pipeline
│ │
│ ├── bin/ # Executable Shell Scripts (Entry Points)
│ │ ├── exec_pipeline.sh # MASTER SCRIPT: Single command to run the experiment
│ │ ├── colab_git_setup...# SYNC SCRIPT: Secure Git cloning/pulling
│ │ └── colab_env_setup.sh# SETUP SCRIPT: Installs Java 17 & mounts Drive
│ │
│ ├── utils/ # Python Utility Package
│ │ ├── cmd_runner.py # Adapter for running shell commands safely
│ │ └── init.py # Exposes utilities to the app
│ │
│ ├── main.py # FACADE: Main Python entry point
│ ├── config.py # CONFIG: All paths (Drive, Tools) and settings
│ ├── repo_metrics.py # ANALYSIS: Project stats (LOC, commits)
│ └── init.py # Package marker
│
├── notebooks/ # Jupyter Notebooks for Colab Control
│ ├── 01_project_setup.ipynb # One-time setup & verification
│ └── 02_pipeline_execution.ipynb # Daily execution trigger
│
└── docs/ # Project Documentation
└── infrastructure_architecture.md
```

---

### B. Persistent Storage (Google Drive: `Thesis_Project/`)

This folder structure is manually created once and persists across Colab sessions.

```commandline
Thesis_Project/
├── tools/ # External Binaries
│ ├── pmd-bin-7.18.0/ # PMD Static Analyzer
│ └── RefactoringMiner_v3/ # RefactoringMiner (built from source)
│
├── repos/ # Input Data
│ └── toy_project/ # 'refactoring-toy-example'
│
├── scripts/ # Code Sync Target
│ └── (The 'smell-ranker' repo is cloned here)
│
└── outputs/ # Experiment Results
├── refactorings.json # Output from Pass 1 (complete history)
└── pmd_report.xml # Output from Pass 2
```

---

## 3. Execution Flow (The “How-To”)

The system is designed to be run from Google Colab, triggered by the  
`02_pipeline_execution.ipynb` notebook.

### Step 1: Initialization

- **Trigger:** User runs `!bash exec_pipeline.sh` in Colab.
- **Action:**  
  `exec_pipeline.sh` detects its location, calculates the repository root, and calls `colab_env_setup.sh`.
- **Result:**  
  - Google Drive is mounted  
  - `openjdk-17-jdk` is installed  
  - `pydriller` is installed  

---

### Step 2: Synchronization

- **Trigger:** `exec_pipeline.sh` calls `colab_git_setup_smell_ranker.sh` with the Git URL.
- **Action:**  
  The script checks whether `Thesis_Project/scripts/` already contains a Git repository.
  - **If No:** runs `git clone` using the injected secure token  
  - **If Yes:** runs `git pull`
- **Result:**  
  The Python code in Google Drive is identical to the local PyCharm/GitHub version.

---

### Step 3: Execution

- **Trigger:**  
  `exec_pipeline.sh` sets executable permissions and calls:

```bash
  python3 -m pipeline.main
 ```

- **Action:**  
- Python starts
- `main.py` imports `config.py` and the adapters module

#### Process

- **Phase 1.5 (Metric Verification):**  
Runs `repo_metrics.py` to print statistics (LOC, commits).

- **Phase 1 (Smoke Test):**  
- Calls `refm_adapt.run_rm_smoke_test()` to iterate all 65 commits and generate `refactorings.json`.
- Calls `pmd_adapt.run_pmd_smoke_test()` to generate `pmd_report.xml`.

---

## 4. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices to ensure thesis defensibility.

| Principle | Implementation |
|---------|----------------|
| Separation of Concerns (SoC) | Logic (`pipeline/`), configuration (`config.py`), and adapters (`pipeline/adapters/`) are distinct |
| Single Responsibility (SRP) | Each adapter handles exactly one tool |
| Facade Pattern | `main.py` acts as the simple entry point |
| Adapter Pattern | Wrappers translate Python calls into tool-specific CLI commands |
| DRY (Don’t Repeat Yourself) | `cmd_runner.py` centralizes subprocess logic |

---

## 5. Toolchain Configuration

### RefactoringMiner

- **Version:** 3.0 (built from source)
- **Build Requirement:** Java 17 (JDK)
- **Role:** Pass 1 – History mining
- **Execution Strategy:**  
*Forced Loop* (explicit iteration over all commits to capture detached/merge history)

---

### PMD

- **Version:** 7.18.0 (binary distribution)
- **Role:** Pass 2 – Candidate generation
- **Detected Smells:** God Class, Long Method, Feature Envy
- **Justification:**  
Chosen over JDeodorant for feasibility and command-line compatibility.

---

## 6. Future Roadmap

- **Phase 2:** Implement `pass_1_fast_scan.py` to parse RefactoringMiner JSON output
- **Phase 3:** Implement `pass_2_slow_analysis.py` to handle Git checkout and PMD loops
- **Phase 4:** Implement `heuristics.py` to score overlap between Pass 1 and Pass 2 data
