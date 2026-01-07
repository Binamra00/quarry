#!/bin/bash
# pipeline/bin/colab_accelerator.sh

# 1. CONSTANTS
DRIVE_WORKSPACE="/content/drive/My Drive/Thesis Project"
FAST_WORKSPACE="/content/fast_workspace"

# Function to Setup the Fast Environment (The "Lift")
init_fast_workspace() {
    local REPO_NAME=$1

    # Send logs to stderr
    echo "🚀 [Accelerator] Initializing Ephemeral Workspace on VM Disk..." >&2

    # Create directories
    mkdir -p "$FAST_WORKSPACE/repos"
    mkdir -p "$FAST_WORKSPACE/tools"
    mkdir -p "$FAST_WORKSPACE/outputs"

    # --- A. LIFT THE REPO ---
    if [ ! -d "$FAST_WORKSPACE/repos/$REPO_NAME" ]; then
        if [ -d "$DRIVE_WORKSPACE/repos/$REPO_NAME" ]; then
             echo "   📦 [Lift] Copying '$REPO_NAME' from Drive..." >&2
             cp -r "$DRIVE_WORKSPACE/repos/$REPO_NAME" "$FAST_WORKSPACE/repos/"
        else
             echo "   ❌ [Lift] Critical: Could not find '$REPO_NAME' in '$DRIVE_WORKSPACE/repos'" >&2
        fi
    else
        echo "   ✨ [Lift] Repo '$REPO_NAME' already exists on Local VM." >&2
    fi

    # --- B. LIFT THE STATE (The Fix) ---
    # Copy existing outputs so the tool knows where to resume
    echo "   📥 [Lift] Copying existing state (outputs) from Drive..." >&2
    # Copy all JSON files (metrics, refactorings, batch status)
    cp "$DRIVE_WORKSPACE/outputs/"* "$FAST_WORKSPACE/outputs/" 2>/dev/null

    # --- C. LINK TOOLS ---
    echo "   🔗 [Link] Symlinking tools from Drive..." >&2
    if [ -d "$DRIVE_WORKSPACE/tools" ]; then
        ln -sfn "$DRIVE_WORKSPACE/tools/"* "$FAST_WORKSPACE/tools/"
    fi

    # Return the path to stdout
    echo "$FAST_WORKSPACE"
}

# Function to Sync Results Back (The "Drop")
sync_results() {
    echo "💾 [Accelerator] Syncing results back to Drive..." >&2
    cp -r "$FAST_WORKSPACE/outputs/"* "$DRIVE_WORKSPACE/outputs/" 2>/dev/null
    echo "   ✅ [Drop] Sync Complete." >&2
}