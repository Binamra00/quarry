#!/bin/bash

# --- Master Pipeline Orchestrator (Universal Edition) ---
# ROLE: Orchestrates the full experiment: Setup -> Sync -> Execute.

# --- 0. ARGUMENT PARSING (ROBUST VERSION) ---
GIT_URL_WITH_TOKEN=""
if [[ -n "$1" && "$1" != -* ]]; then
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

# A. Check Java Version (Strict Check for Java 21+)
REQUIRED_JAVA_VERSION=21
JAVA_INSTALLED=false

if type -p java > /dev/null; then
    # Extract version number (e.g., "21" from "openjdk 21.0.1...")
    CURRENT_JAVA_VERSION=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | cut -d'.' -f1)

    if [[ "$CURRENT_JAVA_VERSION" -ge "$REQUIRED_JAVA_VERSION" ]]; then
        echo "✅ Java $CURRENT_JAVA_VERSION found (Matches requirement >= $REQUIRED_JAVA_VERSION)."
        JAVA_INSTALLED=true
    else
        echo "⚠️ Java $CURRENT_JAVA_VERSION found, but we require Java $REQUIRED_JAVA_VERSION+."
    fi
else
    echo "⚠️ Java NOT found."
fi

# Install Java 21 if missing or too old
if [ "$JAVA_INSTALLED" = false ]; then
    if [ -n "$COLAB_RELEASE_TAG" ]; then
        echo "☁️ Colab detected: Installing/Upgrading to OpenJDK 21..."
        apt-get update > /dev/null
        apt-get install -y openjdk-21-jdk > /dev/null

        # FIX: Force the system to use the new Java version
        update-alternatives --set java /usr/lib/jvm/java-21-openjdk-amd64/bin/java

        echo "✅ Java installed/updated."
        java -version 2>&1 | head -n 1
    else
        echo "❌ ACTION REQUIRED: Please install Java 21+ manually."
        exit 1
    fi
fi

echo "--- Checking Python Libraries ---"
if python3 -c "import pydriller, dotenv, IPython" 2>/dev/null; then
    echo "✅ Python dependencies found."
else
    echo "📦 Installing Python dependencies..."
    pip install pydriller python-dotenv ipython > /dev/null
    echo "✅ Dependencies installed."
fi

# --- 3. CODE SYNC (Optional Layer 2) ---
if [ -n "$GIT_URL_WITH_TOKEN" ]; then
    echo "--- 2. Synchronizing Code from GitHub ---"
    SYNC_SCRIPT="./pipeline/bin/colab_git_setup_smell_ranker.sh"

    if [ -f "$SYNC_SCRIPT" ]; then
        bash "$SYNC_SCRIPT" "$GIT_URL_WITH_TOKEN"
    else
        echo "⚠️ Sync script not found at $SYNC_SCRIPT. Skipping sync."
    fi
else
    echo "--- 3. Skipping Code Sync (No URL provided) ---"
fi

# --- 4. TOOLCHAIN ALLOCATION ---
echo "--- 3. Allocating Toolchain (PMD & RefactoringMiner) ---"
python3 -m pipeline.utils.allocate_tools

if [ $? -ne 0 ]; then
    echo "❌ Tool allocation failed. Check network or allocate_tools.py."
    exit 1
fi

# --- 5. EXECUTE THE PIPELINE ---
echo "--- 4. Starting Pipeline Execution ---"

python3 -m pipeline.main "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Execution Pipeline Complete."
else
    echo "❌ Pipeline Failed."
    exit $exit_code
fi