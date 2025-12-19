import os
import sys
from pathlib import Path

# --- 0. LOAD DOTENV (The New Feature) ---
try:
    from dotenv import load_dotenv

    # Load environment variables from a .env file if it exists
    load_dotenv()
except ImportError:
    # It's okay if dotenv isn't installed in Colab, we fallback to detection
    pass

# --- 1. ROBUST PROJECT ROOT DISCOVERY ---
current_path = Path(__file__).resolve()
root_candidate = current_path.parent
while not (root_candidate / ".git").exists():
    if root_candidate == root_candidate.parent:
        raise RuntimeError("❌ Could not find Project Root (no .git folder found).")
    root_candidate = root_candidate.parent
REPO_ROOT = root_candidate

# --- 2. DYNAMIC WORKSPACE CONFIGURATION ---

# A. Check for Explicit Configuration (The Docker Way)
# If a user sets SMELL_RANKER_HOME in .env or Docker, we use it.
custom_home = os.getenv("SMELL_RANKER_HOME")

# B. Check for Colab (The Research Way)
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

        # Default Colab Path
        WORKSPACE_ROOT = Path("/content/drive/My Drive/Thesis Project")
    except ImportError:
        WORKSPACE_ROOT = Path("/content/workspace_data")

else:
    print("💻 Detected Local Environment (Default).")
    # Default Local Path
    WORKSPACE_ROOT = REPO_ROOT / "workspace_data"

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