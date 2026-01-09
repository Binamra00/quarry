#!/bin/bash

# --- Master Pipeline Orchestrator (Local/Docker Edition) ---
# ROLE: Checks OS dependencies (Java) -> Runs Python Pipeline
# USAGE: ./pipeline/bin/exec_pipeline.sh --repo toy_project

# --- 1. CONTEXT SETUP ---
# Ensure we are running from the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT" || { echo "❌ Failed to cd to $REPO_ROOT"; exit 1; }

# Add current directory to python path so 'pipeline' module is found
export PYTHONPATH=$PYTHONPATH:.

# --- 2. PRE-FLIGHT CHECK: JAVA 21 ---
# Python can download PMD, but it can't install the Java Runtime Environment (JRE).
# We must verify this at the shell level.
REQUIRED_JAVA=21

if type -p java > /dev/null; then
    # Extract version number (e.g., "21.0.1" -> "21")
    JAVA_VER=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | cut -d'.' -f1)

    if [[ "$JAVA_VER" -ge "$REQUIRED_JAVA" ]]; then
        echo "✅ Java $JAVA_VER detected."
    else
        echo "⚠️  WARNING: Java $JAVA_VER detected, but PMD 7 requires Java $REQUIRED_JAVA+."
        echo "    Analysis might fail if version is incompatible."
    fi
else
    echo "❌ CRITICAL: Java not found."
    echo "    Please install OpenJDK 21+ before running the pipeline."
    exit 1
fi

# --- 3. EXECUTE PYTHON PIPELINE ---
# Passes all arguments (like --repo or --stage) directly to main.py
echo "🚀 Starting Smell-Ranker..."
python3 -m pipeline.main "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Run Complete."
else
    echo "❌ Run Failed."
    exit $EXIT_CODE
fi