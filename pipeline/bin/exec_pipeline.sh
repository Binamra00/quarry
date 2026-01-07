#!/bin/bash

# --- Master Pipeline Orchestrator (Universal Edition) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute
#
# USAGE:
#   1. Run Default (Toy Project):
#      !bash exec_pipeline.sh
#
#   2. Run Specific Repo (e.g., Commons-Lang):
#      !bash exec_pipeline.sh --repo commons-lang
#
#   3. Sync & Run (Update pipeline code first):
#      !bash exec_pipeline.sh <GIT_URL> --repo commons-lang

# --- 0. ARGUMENT PARSING (ROBUST VERSION) ---
# Logic: If the first argument is a URL (doesn't start with -), treat it as a Sync Request.
# Otherwise, treat all arguments as flags for the Python pipeline.
GIT_URL_WITH_TOKEN=""
if [[ -n "$1" && "$1" != -* ]]; then
    GIT_URL_WITH_TOKEN="$1"
    # Remove the URL from the arguments list so it doesn't get passed to Python
    shift
fi

# --- 1. PATH CORRECTION & PYTHON CONTEXT ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "--- 0. Setting Context ---"
echo "📂 Repo Root: $REPO_ROOT"
cd "$REPO_ROOT" || { echo "❌ Failed to cd to $REPO_ROOT"; exit 1; }

export PYTHONPATH=$PYTHONPATH:.

# --- 2. SYSTEM DEPENDENCY CHECK ---
echo "--- 1. Checking System Dependencies ---"

# A. Check Java Version (Strict Check for Java 21+)
REQUIRED_JAVA_VERSION=21
JAVA_INSTALLED=false

if type -p java > /dev/null; then
    CURRENT_JAVA_VERSION=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | cut -d'.' -f1)
    if [[ "$CURRENT_JAVA_VERSION" -ge "$REQUIRED_JAVA_VERSION" ]]; then
        echo "✅ Java $CURRENT_JAVA_VERSION found."
        JAVA_INSTALLED=true
    else
        echo "⚠️ Java $CURRENT_JAVA_VERSION found, but we require Java $REQUIRED_JAVA_VERSION+."
    fi
else
    echo "⚠️ Java NOT found."
fi

# Install Java 21 if missing
if [ "$JAVA_INSTALLED" = false ]; then
    if [ -n "$COLAB_RELEASE_TAG" ]; then
        echo "☁️ Colab detected: Installing/Upgrading to OpenJDK 21..."
        apt-get update > /dev/null
        apt-get install -y openjdk-21-jdk > /dev/null
        update-alternatives --set java /usr/lib/jvm/java-21-openjdk-amd64/bin/java
        echo "✅ Java installed/updated."
    else
        echo "❌ ACTION REQUIRED: Please install Java 21+ manually."
        exit 1
    fi
fi

# Check Python Libs (Updated for Testing Framework)
# We check for 'pytest' to ensure the test harness is ready.
if ! python3 -c "import pydriller, dotenv, IPython, pytest" 2>/dev/null; then
    echo "📦 Installing Python dependencies (Runtime + Testing)..."
    # Added pytest and pytest-mock to the installation list
    pip install pydriller python-dotenv ipython pytest pytest-mock > /dev/null
    echo "✅ Dependencies installed."
fi

# --- 3. CODE SYNC (Optional Layer 2) ---
# Only runs if a URL was detected in the first argument
if [ -n "$GIT_URL_WITH_TOKEN" ]; then
    echo "--- 2. Synchronizing Code from GitHub ---"
    SYNC_SCRIPT="./pipeline/bin/colab_git_setup_smell_ranker.sh"
    if [ -f "$SYNC_SCRIPT" ]; then
        bash "$SYNC_SCRIPT" "$GIT_URL_WITH_TOKEN"
    else
        echo "⚠️ Sync script not found. Skipping sync."
    fi
else
    echo "--- 3. Skipping Code Sync (No URL provided) ---"
fi

# --- 4. TOOLCHAIN ALLOCATION ---
echo "--- 3. Allocating Toolchain (PMD & RefactoringMiner) ---"
python3 -m pipeline.utils.allocate_tools
if [ $? -ne 0 ]; then
    echo "❌ Tool allocation failed."
    exit 1
fi

# --- 5. COLAB ACCELERATION (OPTIONAL LAYER) ---
# Only runs in Colab. Prepares the ephemeral workspace.

# 5a. Identify Target Repo (Needed for the Lift operation)
REPO_NAME="toy_project" # Default fallback
NEXT_IS_REPO=0
for arg in "$@"; do
    if [[ "$arg" == "--repo" ]]; then
        NEXT_IS_REPO=1
        continue
    fi
    if [[ "$NEXT_IS_REPO" == 1 ]]; then
        REPO_NAME="$arg"
        NEXT_IS_REPO=0
    fi
done

# 5b. Engage Accelerator
IS_COLAB=0
if [ -n "$COLAB_RELEASE_TAG" ]; then
    IS_COLAB=1
    ACCELERATOR_SCRIPT="./pipeline/bin/colab_accelerator.sh"

    if [ -f "$ACCELERATOR_SCRIPT" ]; then
        echo "--- 3.5. Engaging Cloud Accelerator ---"
        source "$ACCELERATOR_SCRIPT"

        # EXECUTE THE LIFT
        # This function returns the new fast path, which we export for config.py
        export SMELL_RANKER_HOME=$(init_fast_workspace "$REPO_NAME")

        echo "⚡ Environment Configured: SMELL_RANKER_HOME=$SMELL_RANKER_HOME"
    else
        echo "⚠️ Accelerator worker not found ($ACCELERATOR_SCRIPT). Using standard Drive I/O."
    fi
fi

# --- 6. EXECUTE THE PIPELINE ---
echo "--- 4. Starting Pipeline Execution ---"

# [CRITICAL] "$@" passes all remaining arguments (like --repo) to main.py
python3 -m pipeline.main "$@"
EXIT_CODE=$?

# --- 7. SYNC RESULTS (COLAB ONLY) ---
if [ "$IS_COLAB" -eq 1 ] && [ -n "$SMELL_RANKER_HOME" ]; then
    # EXECUTE THE DROP
    # Only runs if the accelerator was actually used
    sync_results
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Execution Pipeline Complete."
else
    echo "❌ Pipeline Failed."
    exit $EXIT_CODE
fi