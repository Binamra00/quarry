import os
import sys
import json
from pathlib import Path

# --- 0. LOAD DOTENV ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
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
custom_home = os.getenv("SMELL_RANKER_HOME")
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
        WORKSPACE_ROOT = REPO_ROOT.parent
    except ImportError:
        WORKSPACE_ROOT = Path("/content/workspace_data")
else:
    print("💻 Detected Local Environment (Default).")
    WORKSPACE_ROOT = REPO_ROOT / "workspace_data"

print(f"📂 Workspace Root: {WORKSPACE_ROOT}")

if not WORKSPACE_ROOT.exists():
    print(f"   ✨ Creating workspace directory: {WORKSPACE_ROOT}")
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# --- 3. DEFINE CORE PATHS ---
TOOLS_PATH = WORKSPACE_ROOT / "tools"
REPOS_PATH = WORKSPACE_ROOT / "repos"
OUTPUTS_PATH = WORKSPACE_ROOT / "outputs"

for path in [TOOLS_PATH, REPOS_PATH, OUTPUTS_PATH]:
    path.mkdir(exist_ok=True)

# --- 4. DEFINE TOOL CONFIGURATION ---
# UPDATE: Changed versions to 7.19.0 and 3.0 to trigger new downloads
PMD_VERSION = "pmd-bin-7.19.0"
RM_VERSION = "RefactoringMiner_3.0"
PMD_PATH = TOOLS_PATH / PMD_VERSION / "bin" / "pmd"
RM_PATH = TOOLS_PATH / RM_VERSION / "bin" / "RefactoringMiner"

# --- 5. TOOL DOWNLOAD URLS (NEW) ---
# Hardcoded to verified versions to ensure stability
PMD_URL = "https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.19.0/pmd-dist-7.19.0-bin.zip"
RM_URL = "https://github.com/tsantalis/RefactoringMiner/releases/download/3.0/RefactoringMiner-3.0.zip"

# --- 6. TARGET REPOSITORIES ---
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 7. INTERNAL ASSETS ---
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"
PMD_RULESET_PATH = RULES_DIR / "pmd_rules_00.xml"

# --- 8. UTILITIES ---
def escape_path(path_obj):
    return str(path_obj).replace(" ", "\\ ")

PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)
WORKSPACE_ROOT_ESCAPED = escape_path(WORKSPACE_ROOT)

# --- 9. HEURISTICS (NEW) ---
HEURISTICS_PATH = REPO_ROOT / "pipeline" / "heuristic_seeds.json"
HEURISTICS = {}

if HEURISTICS_PATH.exists():
    try:
        with open(HEURISTICS_PATH, 'r') as f:
            HEURISTICS = json.load(f)
        print(f"⚙️  Heuristics loaded from {HEURISTICS_PATH.name}")
    except Exception as e:
        print(f"⚠️ Error loading heuristics: {e}")
else:
    print("⚠️ Heuristics file not found. Using internal defaults.")
    # Fallback defaults
    HEURISTICS = {
        "refactoring": {"churn_sensitivity": 20, "purity_target_percent": 80.0, "density_target_percent": 40.0},
        "repo_mining": {
            "fix_keywords": ['fix', 'bug', 'issue'],
            "refactor_keywords": ['refactor', 'cleanup']
        }
    }