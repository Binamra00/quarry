#!/bin/bash

# --- Repository Sync Script (Layer 2: Synchronization) ---
# ROLE: Performs the initial CLONE or the subsequent PULL of the repository.
# REFACTOR: Implemented Dynamic Branch Detection (main vs master).

# $1 is the first argument passed to this script, which MUST be the Git URL.
GIT_REPO_URL="$1"

echo "--- Synchronizing Code from GitHub ---"

# Helper function to detect the default branch from the remote
detect_default_branch() {
    # 1. Fetch remote info to ensure we have the latest pointers
    git remote set-head origin -a > /dev/null 2>&1

    # 2. Ask git for the symbolic ref of origin/HEAD
    # Output is typically: refs/remotes/origin/main OR refs/remotes/origin/master
    FULL_REF=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null)

    # 3. Strip the 'refs/remotes/origin/' prefix
    BRANCH_NAME=${FULL_REF#refs/remotes/origin/}

    # 4. Fallback: If detection fails, default to 'main'
    if [ -z "$BRANCH_NAME" ]; then
        echo "main"
    else
        echo "$BRANCH_NAME"
    fi
}

# Check if the repository has been initialized yet (if .git folder exists)
if [ ! -d ".git" ]; then
    echo "Repository not initialized. initializing new git repo..."

    # Initialize a new git repo
    git init

    # Add the remote
    git remote add origin "$GIT_REPO_URL"

    # Fetch the history
    git fetch origin

    # [FIX] Detect branch dynamically instead of assuming 'main'
    DEFAULT_BRANCH=$(detect_default_branch)
    echo "🔍 Detected Remote HEAD: $DEFAULT_BRANCH"

    # Reset the current directory to match the remote default branch
    git reset --hard "origin/$DEFAULT_BRANCH"

    # Set the upstream tracking information
    git branch --set-upstream-to="origin/$DEFAULT_BRANCH" "$DEFAULT_BRANCH"

    if [ $? -ne 0 ]; then
        echo "Initial setup FAILED. Check URL and PAT."
        exit 1
    fi
else
    # Repository is already initialized.
    echo "Updating existing repository..."

    git fetch origin

    # [FIX] Redetect branch in case it changed or wasn't set
    DEFAULT_BRANCH=$(detect_default_branch)

    # Force reset local changes to match origin's default branch
    git reset --hard "origin/$DEFAULT_BRANCH"

    if [ $? -eq 0 ]; then
        echo "Successfully reset to latest origin/$DEFAULT_BRANCH."
    else
        echo "Reset failed. Trying standard pull..."
        git pull origin "$DEFAULT_BRANCH" || echo "Git pull failed (using existing local files)."
    fi
fi

echo "Code Sync Complete."