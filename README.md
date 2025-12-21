# Smell-Ranker: Infrastructure & Architecture Documentation

**Project:** Automated Code Smell Prioritization and Ranking  
**Version:** 0.4 (Phase 2 – Smoke Test Complete)

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
│ ├── adapters/ # Tool Adapters Package (Adapter Pattern)
│ │ ├── init.py # Exposes adapters to the main pipeline
│ │ ├── i_adapter.py # Interface for all adapters  
│ │ ├── refm_adapt.py # Wrapper for RefactoringMiner CLI logic
│ │ └── pmd_adapt.py # Wrapper for PMD CLI logic
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
│ ├── metrics/ # Metrics classes to generate analysis from adpaters output (Template Method Pattern)
│ │ ├── init.py # Exposes metrics to the main pipeline
│ │ ├── refm_mets.py # Metrics to analyze refm output
│ │ ├── repo_mets.py # Base metrics for all repos
│ │ └── pmd_mets.py # Metrics to analyze PMD output
│ │ └── temp_mets.py # Template to reduce process duplication for adapter metrics classes
│ │
│ │── rulesets/
│ │ └── pmd_rules_00.xml # PMD Ruleset Configuration
│ │ 
│ ├── utils/ # Python Utility Package
│ │ ├── init.py # Exposes utilities to the app
│ │ ├── cmd_subprocess.py # Subprocess for running shell commands safely
│ │ ├── ui.py # Universal Console output formatting
│ │ └── allocate_tools.py # Locates tools in Drive if not present creates them at workspace root
│ │
│ ├── main.py # FACADE: Main Python entry point
│ ├── heuristic_seeds.json # Heuristic Thresholds to guide metirc analysis
│ └──config.py # CONFIG: All paths (Drive, Tools) and settings
│ 
└── docs/ # Project Documentation
│   └── Master Thesis Log.pdf
└── .env
└── .gitignore
└──  requirements.txt
└── .README.md
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
`01_pipeline_execution.ipynb` notebook.

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

- **Phase 0 (Metric Verification):**  
Runs `repo_metrics.py` to mine the total commit history and calculate project stats (LOC, Churn, Age). Generates `repo_metrics_[repo_name].json`.
- **Phase 1 (Analysis - Smoke Test):**  
Calls `refm_adapt.run_rm_smoke_test()` to execute RefactoringMiner.
  - *Forced-Loop Strategy:*  Iterates explicitly through the `git rev-list` to capture all commits, but filters for `*.java` files.
  - Generates `refactorings.json`.
- **Phase 1 (Metrics):** 
    - Parses `refactorings_[repo_name].json` and calls `refm_mets.calculate_refm_metrics()` to calculate:
        - Refactoring Density
        - Commit Purity Score
        - Signal Strength
    - Outputs `refactoring_metrics_[repo_name].json`.
- **Phase 2 (Candidate Generation):**
    - Calls `pmd_adapt.run_pmd_smoke_test()` using the `pmd_rules_00.xml` ruleset to generate `pmd_candidates_toy_project.json`.
- **Phase 2 (Metrics):** 
    - Parses `pmd_[repo_name].json` and calls `pmd_mets.calculate_pmd_metrics()` to calculate:
        - Smell Density
        - Smell Intensity
        - Rule Taxanomy
        - Method Complexity Mean
    - Outputs `pmd_metrics_[repo_name].json`.
---

## 4. Design Principles & Patterns

The architecture adheres strictly to software engineering best practices to ensure thesis defensibility.

| Principle | Implementation |
|----------|----------------|
| Separation of Concerns (SoC) | Logic (`pipeline/`), configuration (`config.py`), and adapters (`pipeline/adapters/`) are strictly distinct. |
| Single Responsibility (SRP) | Each adapter handles exactly one tool; `ui.py` handles strictly display logic. |
| Command Pattern | `main.py` (Invoker) executes encapsulated `RunToolCommand` objects, decoupling the request from the execution. |
| Adapter Pattern | `IAdapter` interface standardizes diverse tools (Java-based PMD, Git-based RefactoringMiner) into a uniform Python contract. |
| Open/Closed Principle (OCP) | The pipeline is open for extension (add new `SonarAdapter`) but closed for modification (no changes needed in `main.py`). |
| Strategy Pattern | `ui.py` dynamically selects the visualization strategy (Jupyter Widget vs. standard `\r`) based on the runtime environment. |
| DRY (Don’t Repeat Yourself) | `cmd_subprocess.py` centralizes all shell execution, error handling, and file streaming logic. |


---

## 5. Toolchain Configuration

### RefactoringMiner

- **Version:** 3.0 (built from source)
- **Build Requirement:** Java 17 (JDK)
- **Role:** Pass 1 – History mining
- **Execution Strategy:**  
*Forced Loop* (explicit iteration over all commits via git rev-list --all --reverse -- *.java). This captures detached/merge history while filtering out non-code noise (e.g., docs/builds).

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
