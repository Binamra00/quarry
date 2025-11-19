#!/bin/bash

# --- Runtime Initialization Script ---
# This script handles mounting Google Drive and installing core dependencies
# needed by the pipeline tools (RefactoringMiner, PMD).

# 1. Mount Google Drive (if not already mounted)
if [ ! -d "/content/drive/My Drive" ]; then
    echo "Mounting Google Drive..."
    /usr/bin/python3 -c "from google.colab import drive; drive.mount('/content/drive')"
else
    echo "Google Drive already mounted."
fi

# 2. Install Runtime Dependencies (Java 17)
# Note: We suppress output ( > /dev/null 2>&1 ) for a cleaner console.
echo "Initializing Environment (Java 17)..."
sudo apt-get update > /dev/null 2>&1
sudo apt-get install -y openjdk-17-jdk > /dev/null 2>&1

# Verify the version for confirmation
JAVA_VERSION=$(java -version 2>&1 | awk '/version/ {print $3}')
echo "Environment Ready. Java version: $JAVA_VERSION"