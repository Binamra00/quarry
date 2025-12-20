#!/bin/bash

# --- Master Pipeline Orchestrator (Universal Edition) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute.
# NOW SUPPORTED: Local Linux/Mac and Google Colab.

# $1 is the optional Git URL for syncing (Layer 2).
GIT_URL_WITH_TOKEN="$1"

# --- 0. PATH CORRECTION & PYTHON CONTEXT ---
# Determine where this script is, then find the Repo Root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Go up two levels: pipeline/bin -> pipeline -> REPO_ROOT
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "--- 0. Setting Context ---"
echo "📂 Repo Root: $REPO_ROOT"
cd "$REPO_ROOT" || { echo "❌ Failed to cd to $REPO_ROOT"; exit 1; }

# CRITICAL: Add current directory to PYTHONPATH so 'pipeline' module is found
export PYTHONPATH=$PYTHONPATH:.


# --- 1. SYSTEM DEPENDENCY CHECK (Java & Python Libs) ---
echo "--- 1. Checking System Dependencies ---"

# A. Check Java 17 (Required for RefactoringMiner)
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

# B. Check Python Libraries
echo "--- Checking Python Libraries ---"
# We check for both pydriller and python-dotenv
if python3 -c "import pydriller, dotenv" 2>/dev/null; then
    echo "✅ Python dependencies found."
else
    echo "📦 Installing Python dependencies..."
    pip install pydriller python-dotenv > /dev/null
    echo "✅ Dependencies installed."
fi


# --- 2. TOOLCHAIN ALLOCATION (The New Feature) ---
# This replaces manual downloads and chmod commands.
echo "--- 2. Allocating Toolchain (PMD & RefactoringMiner) ---"
python3 -m pipeline.utils.allocate_tools

if [ $? -ne 0 ]; then
    echo "❌ Tool allocation failed. Check network or allocate_tools.py."
    exit 1
fi


# --- 3. CODE SYNC (Optional Layer 2) ---
# Only runs if a Git URL is provided (useful for Colab auto-updating).
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


# --- 4. EXECUTE THE PIPELINE ---
echo "--- 4. Starting Pipeline Execution ---"

# UPDATED: We use "$@" to pass ALL arguments from this shell script
# to the Python main module.
# Example: ./exec_pipeline.sh --stage static  -> python ... main --stage static
python3 -m pipeline.main "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Execution Pipeline Complete."
else
    echo "❌ Pipeline Failed."
    exit $exit_code
fi