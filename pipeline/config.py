import os
import sys
from pathlib import Path

# --- 1. ROBUST PROJECT ROOT DISCOVERY ---
# Traverses up until it finds .git to establish the Codebase Root
current_path = Path(__file__).resolve()
root_candidate = current_path.parent

while not (root_candidate / ".git").exists():
    if root_candidate == root_candidate.parent:  # Hit filesystem root
        raise RuntimeError("❌ Could not find Project Root (no .git folder found).")
    root_candidate = root_candidate.parent

REPO_ROOT = root_candidate

# --- 2. ENVIRONMENT DETECTION & WORKSPACE SETUP ---
# We detect Colab by checking specific environment variables.
IS_COLAB = "COLAB_RELEASE_TAG" in os.environ or "COLAB_GPU" in os.environ

print(f"📂 Codebase Root: {REPO_ROOT}")

if IS_COLAB:
    print("☁️ Detected Google Colab Environment.")
    try:
        from google.colab import drive

        # Only mount if not already mounted
        if not os.path.exists("/content/drive"):
            print("   ⏳ Mounting Google Drive...")
            drive.mount('/content/drive')

        # Define the Persistent Workspace in Drive
        # NOTE: Ensure this folder exists in your Drive or the script will create it
        WORKSPACE_ROOT = Path("/content/drive/My Drive/Thesis Project")
    except ImportError:
        print("⚠️ Error importing google.colab. Falling back to local /content storage.")
        WORKSPACE_ROOT = Path("/content/workspace_data")
else:
    print("💻 Detected Local Environment.")
    # Local workspace inside the repo (should be gitignored)
    WORKSPACE_ROOT = REPO_ROOT / "workspace_data"

# Create the Workspace Root if it doesn't exist
if not WORKSPACE_ROOT.exists():
    print(f"   ✨ Creating workspace directory: {WORKSPACE_ROOT}")
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# --- 3. DEFINE CORE PATHS ---
# These live INSIDE the Workspace (Drive or Local)
TOOLS_PATH = WORKSPACE_ROOT / "tools"
REPOS_PATH = WORKSPACE_ROOT / "repos"
OUTPUTS_PATH = WORKSPACE_ROOT / "outputs"

# Auto-create subdirectories
for path in [TOOLS_PATH, REPOS_PATH, OUTPUTS_PATH]:
    path.mkdir(exist_ok=True)

# --- 4. DEFINE TOOL CONFIGURATION ---
# We define versions here so setup_tools.py can use them
PMD_VERSION = "pmd-bin-7.18.0"
RM_VERSION = "RefactoringMiner_v3"

# Tool Executables
PMD_PATH = TOOLS_PATH / PMD_VERSION / "bin" / "pmd"
RM_PATH = TOOLS_PATH / RM_VERSION / "bin" / "RefactoringMiner"

# --- 5. TARGET REPOSITORIES ---
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 6. INTERNAL ASSETS (Codebase) ---
# These files live in the Git Repo, not the Workspace
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"
PMD_RULESET_PATH = RULES_DIR / "pmd_rules_00.xml"


# --- 7. UTILITIES ---
def escape_path(path_obj):
    """Escapes a pathlib.Path object for safe use in a shell command."""
    return str(path_obj).replace(" ", "\\ ")


# Pre-escaped paths for shell usage
PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)

# --- 8. HEURISTICS & CONSTANTS (Placeholder for Sunday) ---
# Defining them here prevents magic numbers in metrics scripts
CHURN_THRESHOLD = 20