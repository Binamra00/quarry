#!/bin/bash
# pipeline/bin/colab_accelerator.sh

# 1. CONSTANTS
# [FIX] Matched to your screenshot: direct access to "Thesis Project"
DRIVE_WORKSPACE="/content/drive/My Drive/Thesis Project"

FAST_WORKSPACE="/content/fast_workspace"

# Function to Setup the Fast Environment (The "Lift")
init_fast_workspace() {
    local REPO_NAME=$1

    # Send logs to stderr so they don't pollute the return value
    echo "🚀 [Accelerator] Initializing Ephemeral Workspace on VM Disk..." >&2

    # Create directories
    mkdir -p "$FAST_WORKSPACE/repos"
    mkdir -p "$FAST_WORKSPACE/tools"
    mkdir -p "$FAST_WORKSPACE/outputs"

    # Copy Repo (Only if missing)
    if [ ! -d "$FAST_WORKSPACE/repos/$REPO_NAME" ]; then
        if [ -d "$DRIVE_WORKSPACE/repos/$REPO_NAME" ]; then
             echo "   📦 [Lift] Copying '$REPO_NAME' from Drive to Local VM..." >&2
             cp -r "$DRIVE_WORKSPACE/repos/$REPO_NAME" "$FAST_WORKSPACE/repos/"
        else
             echo "   ❌ [Lift] Critical: Could not find '$REPO_NAME' in '$DRIVE_WORKSPACE/repos'" >&2
        fi
    else
        echo "   ✨ [Lift] Repo '$REPO_NAME' already exists on Local VM." >&2
    fi

    # Link Tools (Symlink to avoid re-downloading)
    echo "   🔗 [Link] Symlinking tools from Drive..." >&2

    if [ -d "$DRIVE_WORKSPACE/tools" ]; then
        # Use -f to force overwrite if link exists, -n to treat dest as normal file
        ln -sfn "$DRIVE_WORKSPACE/tools/"* "$FAST_WORKSPACE/tools/"
    else
        echo "   ⚠️ [Lift] Warning: Tools folder not found in Drive. Pipeline might download them again." >&2
    fi

    # [CRITICAL] Return the path to stdout
    echo "$FAST_WORKSPACE"
}

# Function to Sync Results Back (The "Drop")
sync_results() {
    echo "💾 [Accelerator] Syncing results back to Drive..." >&2

    # Sync outputs directly to Thesis Project/outputs
    cp -r "$FAST_WORKSPACE/outputs/"* "$DRIVE_WORKSPACE/outputs/" 2>/dev/null

    # Explicitly sync batch status files for resume capability
    cp "$FAST_WORKSPACE/outputs/batch_status_"* "$DRIVE_WORKSPACE/outputs/" 2>/dev/null

    echo "   ✅ [Drop] Sync Complete." >&2
}