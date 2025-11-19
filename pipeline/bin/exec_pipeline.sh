#!/bin/bash

# --- Master Pipeline Orchestrator (Layer 3: Execution Master) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute Python.

# $1 is the first argument passed to this script, which MUST be the Git URL.
GIT_URL_WITH_TOKEN="$1" # <--- CAPTURES THE URL PASSED FROM COLAB

# --- Define Sub-Scripts (Paths are relative to the current directory: pipeline/bin) ---
ENV_SETUP_SCRIPT="./colab_env_setup.sh"
GIT_SYNC_SCRIPT="./colab_git_setup_smell_ranker.sh"
MAIN_PYTHON_MODULE="pipeline.main"

# --- Define Python Binaries for Executability (CRITICAL AFTER SYNC) ---
PYTHON_BINARIES=(
    "./pipeline/main.py"
)

# --- 1. ENV SETUP (Call Layer 1) ---
# This must run first to ensure Java is installed and the Drive is mounted.
echo "--- 1. Initializing Runtime Environment (Java/Mount) ---"
bash "$ENV_SETUP_SCRIPT"

# --- 2. CODE SYNC (Call Layer 2) ---
# FIX: Pass the critical URL to the synchronization script.
echo "--- 2. Synchronizing Code from GitHub ---"
bash "$GIT_SYNC_SCRIPT" "$GIT_URL_WITH_TOKEN"

# --- 3. ENFORCE EXECUTABILITY (After Sync) ---
# This is crucial as Git does not preserve executable permissions.
echo "--- 3. Enforcing Script Permissions ---"
for file in "${PYTHON_BINARIES[@]}"; do
    chmod +x "$file" || echo "Warning: Could not set executable permission on $file"
done

# --- 4. EXECUTE THE PIPELINE ---
echo "--- 4. Starting Pipeline Execution ---"
/usr/bin/python3 -m "$MAIN_PYTHON_MODULE"

echo "✅ Execution Pipeline Complete."