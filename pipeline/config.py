import os
import sys
from pathlib import Path

# --- 0. LOAD DOTENV ---
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- 1. ROBUST PROJECT ROOT DISCOVERY ---
# This finds the folder containing .git (e.g., .../Thesis Project/scripts)
current_path = Path(__file__).resolve()
root_candidate = current_path.parent
while not (root_candidate / ".git").exists():
    if root_candidate == root_candidate.parent:
        raise RuntimeError("❌ Could not find Project Root (no .git folder found).")
    root_candidate = root_candidate.parent
REPO_ROOT = root_candidate

# --- 2. DYNAMIC WORKSPACE CONFIGURATION ---

# A. Check for Explicit Configuration (.env override)
custom_home = os.getenv("SMELL_RANKER_HOME")

# B. Check for Colab
is_colab = "COLAB_RELEASE_TAG" in os.environ or "COLAB_GPU" in os.environ

print(f"📂 Codebase Root: {REPO_ROOT}")

if custom_home:
    print(f"⚙️  Custom Config Detected: SMELL_RANKER_HOME={custom_home}")
    WORKSPACE_ROOT = Path(custom_home)

elif is_colab:
    print("☁️  Detected Google Colab Environment.")
    try:
        from google.colab import drive

        if not os.path.exists("/content/drive"):
            print("   ⏳ Mounting Google Drive...")
            drive.mount('/content/drive')

        # [CRITICAL FIX] DYNAMIC PARENT RESOLUTION
        # Instead of hardcoding "/content/drive/My Drive/Thesis_Project",
        # we trust that the 'scripts' repo is inside the Workspace folder.
        # Workspace = Parent of Repo Root
        WORKSPACE_ROOT = REPO_ROOT.parent

    except ImportError:
        WORKSPACE_ROOT = Path("/content/workspace_data")

else:
    print("💻 Detected Local Environment (Default).")
    # In local mode, we usually want the workspace INSIDE the repo to keep it contained
    WORKSPACE_ROOT = REPO_ROOT / "workspace_data"

print(f"📂 Workspace Root: {WORKSPACE_ROOT}")

# Create the Workspace Root if it doesn't exist
if not WORKSPACE_ROOT.exists():
    print(f"   ✨ Creating workspace directory: {WORKSPACE_ROOT}")
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# --- 3. DEFINE CORE PATHS ---
TOOLS_PATH = WORKSPACE_ROOT / "tools"
REPOS_PATH = WORKSPACE_ROOT / "repos"
OUTPUTS_PATH = WORKSPACE_ROOT / "outputs"

# Auto-create subdirectories
for path in [TOOLS_PATH, REPOS_PATH, OUTPUTS_PATH]:
    path.mkdir(exist_ok=True)

# --- 4. DEFINE TOOL CONFIGURATION ---
PMD_VERSION = "pmd-bin-7.18.0"
RM_VERSION = "RefactoringMiner_v3"
PMD_PATH = TOOLS_PATH / PMD_VERSION / "bin" / "pmd"
RM_PATH = TOOLS_PATH / RM_VERSION / "bin" / "RefactoringMiner"

# --- 5. TARGET REPOSITORIES ---
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 6. INTERNAL ASSETS ---
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"
PMD_RULESET_PATH = RULES_DIR / "pmd_rules_00.xml"


# --- 7. UTILITIES ---
def escape_path(path_obj):
    return str(path_obj).replace(" ", "\\ ")


PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)
WORKSPACE_ROOT_ESCAPED = escape_path(WORKSPACE_ROOT)

# --- 8. HEURISTICS (Placeholder) ---
CHURN_THRESHOLD = 20