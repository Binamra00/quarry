#!/bin/bash

# --- Repository Sync Script (Layer 2: Synchronization) ---
# ROLE: Performs the initial CLONE or the subsequent PULL of the repository.

# $1 is the first argument passed to this script, which MUST be the Git URL.
GIT_REPO_URL="$1"

echo "--- Synchronizing Code from GitHub ---"

# Check if the repository has been initialized yet (if .git folder exists)
if [ ! -d ".git" ]; then
    echo "Repository not initialized. initializing new git repo..."

    # Initialize a new git repo
    git init

    # Add the remote
    git remote add origin "$GIT_REPO_URL"

    # Fetch the history
    git fetch origin

    # Reset the current directory to match the remote main branch
    # This overwrites existing files with the versions from GitHub.
    git reset --hard origin/main

    # Set the upstream tracking information
    git branch --set-upstream-to=origin/main main

    if [ $? -ne 0 ]; then
        echo "Initial setup FAILED. Check URL and PAT."
        exit 1
    fi
else
    # Repository is already initialized.
    echo "Updating existing repository..."

    # FIX: Force reset local changes to match origin/main
    # This prevents "local changes would be overwritten" errors
    git fetch origin
    git reset --hard origin/main

    if [ $? -eq 0 ]; then
        echo "Successfully reset to latest origin/main."
    else
        echo "Reset failed. Trying standard pull..."
        git pull origin main || echo "Git pull failed (using existing local files)."
    fi
fi

echo "Code Sync Complete."