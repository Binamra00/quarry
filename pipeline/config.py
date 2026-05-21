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

print(f"📂 Codebase Root: {REPO_ROOT}")

# Streamlined logic: Either use the custom env var OR default to local workspace_data
if custom_home:
    print(f"⚙️  Custom Config Detected: SMELL_RANKER_HOME={custom_home}")
    WORKSPACE_ROOT = Path(custom_home)
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
VERSIONS_PATH = WORKSPACE_ROOT / "versions"

for path in [TOOLS_PATH, REPOS_PATH, OUTPUTS_PATH, VERSIONS_PATH]:
    path.mkdir(exist_ok=True)

# --- 4. TOOL CONFIGURATION ---
PMD_VERSION = "pmd-bin-7.19.0"
RM_VERSION = "RefactoringMiner-3.0.12"

# SECURITY: SHA-256 Checksums
PMD_SHA256 = "beccb2c9c2abfd2e974a29f843a3d54565ce01bbf80fda947072fe10b4a2d3f0"
RM_SHA256 = "cc15a9cc9c2805583043f11434554d56471680671e13341ecf7d550fb253dfcb"

# Tool Internals
RM_ENTRY_POINT_CLASS = "org.refactoringminer.RefactoringMiner"

# Determine extension based on OS (Windows requires .bat)
if os.name == 'nt':
    PMD_EXEC = "pmd.bat"
    RM_EXEC = "RefactoringMiner.bat"
else:
    PMD_EXEC = "pmd"
    RM_EXEC = "RefactoringMiner"

PMD_PATH = TOOLS_PATH / PMD_VERSION / "bin" / PMD_EXEC
RM_PATH = TOOLS_PATH / RM_VERSION / "bin" / RM_EXEC

# --- 5. TOOL DOWNLOAD URLS ---
PMD_URL = "https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.19.0/pmd-dist-7.19.0-bin.zip"
RM_URL = "https://github.com/tsantalis/RefactoringMiner/releases/download/3.0.12/RefactoringMiner-3.0.12.zip"

# --- 6. TARGET REPOSITORIES ---
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 7. INTERNAL ASSETS ---
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"
PMD_RULESET_PATH = RULES_DIR / "pmd_rules_00.xml"

# --- 8. UTILITIES ---
def escape_path(path_obj):
    return str(path_obj).replace(" ", "\\\\ ")

PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)
WORKSPACE_ROOT_ESCAPED = escape_path(WORKSPACE_ROOT)

# --- 9. HEURISTICS ---
# HEURISTICS_PATH = REPO_ROOT / "pipeline" / "heuristic_seeds.json"
# HEURISTICS = {}
#
# if HEURISTICS_PATH.exists():
#     try:
#         with open(HEURISTICS_PATH, 'r') as f:
#             HEURISTICS = json.load(f)
#         print(f"⚙️  Heuristics loaded from {HEURISTICS_PATH.name}")
#     except Exception as e:
#         print(f"⚠️ Error loading heuristics: {e}")
# else:
#     print("⚠️ Heuristics file not found. Using internal defaults.")
#     HEURISTICS = {
#         "refactoring": {"churn_sensitivity": 20, "purity_target_percent": 80.0, "density_target_percent": 40.0},
#         "repo_mining": {
#             "fix_keywords": ['fix', 'bug', 'issue'],
#             "refactor_keywords": ['refactor', 'cleanup']
#         }
#     }

# --- 10. CONSTANTS ---
VALID_STAGES = ["all", "meta", "refm", "pmd", "pmd_history"]

# --- 11. I/O RESILIENCE CONFIGURATION ---
IO_MAX_RETRIES = 5
IO_RETRY_DELAY_BASE = 0.1