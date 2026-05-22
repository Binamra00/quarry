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

if custom_home and custom_home.strip():
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

# --- 4. TOOL CONFIGURATION (From .env or Defaults) ---
STRUCTURAL_TOOL = os.getenv("STRUCTURAL_TOOL", "ck").lower().strip()

# 4A. CK Tool (Structural Taxonomy)
CK_VERSION = os.getenv("CK_VERSION", "0.7.0")
CK_JAR_NAME = f"ck-{CK_VERSION}-jar-with-dependencies.jar"
CK_URL = os.getenv(
    "CK_URL",
    f"https://repo1.maven.org/maven2/com/github/mauricioaniche/ck/{CK_VERSION}/{CK_JAR_NAME}"
)
CK_SHA256 = os.getenv("CK_SHA256", "REPLACE_WITH_ACTUAL_CK_0_7_0_HASH")
CK_PATH = TOOLS_PATH / "ck" / CK_JAR_NAME

# 4B. PMD Tool (Legacy/Alternative)
PMD_VERSION = os.getenv("PMD_VERSION", "7.24.0")
PMD_URL = os.getenv(
    "PMD_URL",
    f"https://github.com/pmd/pmd/releases/download/pmd_releases%2F{PMD_VERSION}/pmd-dist-{PMD_VERSION}-bin.zip"
)
PMD_SHA256 = os.getenv("PMD_SHA256", "REPLACE_WITH_ACTUAL_PMD_7_24_0_HASH")

if os.name == 'nt':
    PMD_EXEC = "pmd.bat"
else:
    PMD_EXEC = "pmd"
PMD_PATH = TOOLS_PATH / f"pmd-bin-{PMD_VERSION}" / "bin" / PMD_EXEC

# 4C. RefactoringMiner Tool
RM_VERSION = os.getenv("RM_VERSION", "3.1.3")
RM_URL = os.getenv(
    "RM_URL",
    f"https://github.com/tsantalis/RefactoringMiner/releases/download/{RM_VERSION}/RefactoringMiner-{RM_VERSION}.zip"
)
RM_SHA256 = os.getenv("RM_SHA256", "71be3a02d9e116340b6532a821f1cd2aea126cbf81aeb894905b9cc19099ee4d")
RM_ENTRY_POINT_CLASS = "org.refactoringminer.RefactoringMiner"

if os.name == 'nt':
    RM_EXEC = "RefactoringMiner.bat"
else:
    RM_EXEC = "RefactoringMiner"
RM_PATH = TOOLS_PATH / f"RefactoringMiner-{RM_VERSION}" / "bin" / RM_EXEC

# --- 5. TARGET REPOSITORIES & INTERNAL ASSETS ---
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"
PMD_RULESET_PATH = RULES_DIR / "pmd_rules_00.xml"

# --- 6. UTILITIES ---
def escape_path(path_obj):
    return str(path_obj).replace(" ", "\\\\ ")

CK_PATH_ESCAPED = escape_path(CK_PATH)
PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
WORKSPACE_ROOT_ESCAPED = escape_path(WORKSPACE_ROOT)

# --- 7. CONSTANTS ---
# Fully supports both the old PMD workflow and the new CK/History workflow
VALID_STAGES = ["all", "meta", "refm", "pmd", "pmd_history", "ck", "ledger"]

# --- 8. I/O RESILIENCE CONFIGURATION ---
IO_MAX_RETRIES = int(os.getenv("IO_MAX_RETRIES", "5"))
IO_RETRY_DELAY_BASE = float(os.getenv("IO_RETRY_DELAY_BASE", "0.1"))