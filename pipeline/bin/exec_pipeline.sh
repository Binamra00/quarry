#!/bin/bash

# --- Master Pipeline Orchestrator (Layer 3: Execution Master) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute Python.

# $1 is the first argument passed to this script, which MUST be the Git URL.
GIT_URL_WITH_TOKEN="$1"

# --- 0. PATH CORRECTION (CRITICAL FIX) ---
# We must ensure we are running from the correct directory.
# This logic finds where this script is located and navigates to the repo root.

# Get the directory where this script lives (e.g., .../pipeline/bin)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Calculate the Repo Root (Go up two levels: pipeline/bin -> pipeline -> root)
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "--- 0. Setting Working Directory ---"
echo "Script Location: $SCRIPT_DIR"
echo "Repo Root:       $REPO_ROOT"

# Change directory to the Repo Root so that 'pipeline' is a valid package
cd "$REPO_ROOT" || { echo "Failed to cd to $REPO_ROOT"; exit 1; }

# Add the current directory to PYTHONPATH so python can find 'pipeline'
export PYTHONPATH=$PYTHONPATH:.


# --- Define Sub-Scripts (Now relative to REPO_ROOT) ---
# Since we are now at the root, the bin scripts are at pipeline/bin/
ENV_SETUP_SCRIPT="./pipeline/bin/colab_env_setup.sh"
GIT_SYNC_SCRIPT="./pipeline/bin/colab_git_setup_smell_ranker.sh"
MAIN_PYTHON_MODULE="pipeline.main"


# --- 1. ENV SETUP (Call Layer 1) ---
echo "--- 1. Initializing Runtime Environment (Java/Mount) ---"
if [ -f "$ENV_SETUP_SCRIPT" ]; then
    bash "$ENV_SETUP_SCRIPT"
else
    echo "ERROR: Could not find environment script at $ENV_SETUP_SCRIPT"
    exit 1
fi

# --- 2. CODE SYNC (Call Layer 2) ---
echo "--- 2. Synchronizing Code from GitHub ---"
if [ -f "$GIT_SYNC_SCRIPT" ]; then
    bash "$GIT_SYNC_SCRIPT" "$GIT_URL_WITH_TOKEN"
else
    echo "ERROR: Could not find sync script at $GIT_SYNC_SCRIPT"
    exit 1
fi

# --- 3. EXECUTE THE PIPELINE ---
echo "--- 3. Starting Pipeline Execution ---"
# We run the module using the package syntax (-m pipeline.main)
/usr/bin/python3 -m "$MAIN_PYTHON_MODULE"

echo "✅ Execution Pipeline Complete."