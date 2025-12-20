#!/bin/bash

# --- Master Pipeline Orchestrator (Universal Edition) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute.

# --- 0. ARGUMENT PARSING (The Critical Fix) ---
# We check if the first argument is a URL (starts with http).
# If yes, we capture it and SHIFT it out.
# This ensures $1 becomes '--stage' and the URL is NOT passed to Python.
GIT_URL_WITH_TOKEN=""
if [[ "$1" == http* ]]; then
    GIT_URL_WITH_TOKEN="$1"
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

if type -p java > /dev/null; then
    echo "✅ Java found."
else
    echo "⚠️ Java NOT found."
    if [ -n "$COLAB_RELEASE_TAG" ]; then
        echo "☁️ Colab detected: Installing OpenJDK 17..."
        apt-get update > /dev/null
        apt-get install -y openjdk-17-jdk > /dev/null
        echo "✅ Java installed."
    else
        echo "❌ ACTION REQUIRED: Please install Java 17+ manually."
        exit 1
    fi
fi

echo "--- Checking Python Libraries ---"
if python3 -c "import pydriller, dotenv" 2>/dev/null; then
    echo "✅ Python dependencies found."
else
    echo "📦 Installing Python dependencies..."
    pip install pydriller python-dotenv > /dev/null
    echo "✅ Dependencies installed."
fi

# --- 3. TOOLCHAIN ALLOCATION ---
echo "--- 2. Allocating Toolchain (PMD & RefactoringMiner) ---"
python3 -m pipeline.utils.allocate_tools

if [ $? -ne 0 ]; then
    echo "❌ Tool allocation failed. Check network or allocate_tools.py."
    exit 1
fi

# --- 4. CODE SYNC (Optional Layer 2) ---
if [ -n "$GIT_URL_WITH_TOKEN" ]; then
    echo "--- 3. Synchronizing Code from GitHub ---"
    SYNC_SCRIPT="./pipeline/bin/colab_git_setup_smell_ranker.sh"

    if [ -f "$SYNC_SCRIPT" ]; then
        bash "$SYNC_SCRIPT" "$GIT_URL_WITH_TOKEN"
    else
        echo "⚠️ Sync script not found at $SYNC_SCRIPT. Skipping sync."
    fi
else
    echo "--- 3. Skipping Code Sync (No URL provided) ---"
fi

# --- 5. EXECUTE THE PIPELINE ---
echo "--- 4. Starting Pipeline Execution ---"

# Now "$@" only contains the flags (like --stage pmd), because the URL was shifted out.
python3 -m pipeline.main "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Execution Pipeline Complete."
else
    echo "❌ Pipeline Failed."
    exit $exit_code
fi