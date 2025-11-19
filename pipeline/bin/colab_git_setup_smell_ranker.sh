#!/bin/bash

# --- Repository Sync Script (Layer 2: Synchronization) ---
# ROLE: Performs the initial CLONE or the subsequent PULL of the repository.

# $1 is the first argument passed to this script, which MUST be the Git URL.
GIT_REPO_URL="$1"

echo "--- Synchronizing Code from GitHub ---"

# Check if the repository has been initialized yet (if .git folder exists)
if [ ! -d ".git" ]; then
    echo "Repository not initialized. Performing initial CLONE."

    # Clone the repository using the URL passed from the master script.
    # The clone action creates the .git/config file that permanently stores the URL.
    git clone "$GIT_REPO_URL" .

    if [ $? -ne 0 ]; then
        echo "Initial clone FAILED. Check URL and PAT."
        exit 1
    fi
else
    # Repository is already initialized, just pull the latest changes.
    echo "Pulling latest changes..."
    # FIX: Use the robust pull command.
    git pull origin main || echo "Git pull failed (using existing local files)."
fi

echo "Code Sync Complete."