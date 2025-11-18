#!/bin/bash

# --- Master Pipeline Orchestrator (git_smell_ranker_setup.sh) ---
# This is the single entry point for running the entire experiment.
# It ensures sync, environment setup, and pipeline execution run in sequence.

# Define variables needed for execution, relative to the current working directory (SCRIPT_ROOT)
SETUP_SCRIPT="./pipeline/bin/colab_env_setup.sh"  # Assuming you renamed the env setup script
MAIN_PYTHON_MODULE="pipeline.main"

# --- 1. Synchronize Code ---
# This pulls the latest code (including this script itself) from GitHub.
echo "--- 1. Synchronizing Code from GitHub ---"
# We explicitly allow failure here due to known external server issues (500).
git pull || echo "Git pull failed (server or initial clone issue). Using existing local files."

# --- 2. Execute Runtime Setup ---
# Runs the environment setup (Mount Drive, Install Java)
echo "--- 2. Initializing Runtime Environment (Java/Mount) ---"
# Ensure the setup script is executable
chmod +x "$SETUP_SCRIPT"
bash "$SETUP_SCRIPT"

# --- 3. EXECUTE THE PIPELINE ---
echo "--- 3. Starting Pipeline Execution ---"
# Execute the Python module using the installed package name 'pipeline'
/usr/bin/python3 -m "$MAIN_PYTHON_MODULE"

echo "✅ Pipeline Orchestration Complete."