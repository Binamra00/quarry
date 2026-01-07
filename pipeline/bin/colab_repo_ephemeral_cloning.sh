#!/bin/bash
# pipeline/bin/colab_accelerator.sh

# 1. CONSTANTS
DRIVE_WORKSPACE="/content/drive/My Drive/Thesis Project/workspace_data"
FAST_WORKSPACE="/content/fast_workspace"

# Function to Setup the Fast Environment (The "Lift")
init_fast_workspace() {
    local REPO_NAME=$1
    echo "🚀 [Accelerator] Initializing Ephemeral Workspace on VM Disk..."

    # Create directories
    mkdir -p "$FAST_WORKSPACE/repos"
    mkdir -p "$FAST_WORKSPACE/tools"
    mkdir -p "$FAST_WORKSPACE/outputs"

    # Copy Repo (Only if missing to save time on re-runs)
    if [ ! -d "$FAST_WORKSPACE/repos/$REPO_NAME" ]; then
        echo "   📦 [Lift] Copying '$REPO_NAME' from Drive to Local VM..."
        cp -r "$DRIVE_WORKSPACE/repos/$REPO_NAME" "$FAST_WORKSPACE/repos/"
    else
        echo "   ✨ [Lift] Repo '$REPO_NAME' already exists on Local VM."
    fi

    # Link Tools (Symlink to avoid re-downloading)
    echo "   🔗 [Link] Symlinking tools from Drive..."
    # We use -n to avoid dereferencing if link exists
    ln -sfn "$DRIVE_WORKSPACE/tools/"* "$FAST_WORKSPACE/tools/"

    # Return the new home path to the caller
    echo "$FAST_WORKSPACE"
}

# Function to Sync Results Back (The "Drop")
sync_results() {
    echo "💾 [Accelerator] Syncing results back to Drive..."
    # Copy all JSON/JSONL outputs
    cp -r "$FAST_WORKSPACE/outputs/"* "$DRIVE_WORKSPACE/outputs/" 2>/dev/null

    # CRITICAL: Sync the Batch State so we can resume later!
    cp "$FAST_WORKSPACE/outputs/batch_status_"* "$DRIVE_WORKSPACE/outputs/" 2>/dev/null

    echo "   ✅ [Drop] Sync Complete."
}