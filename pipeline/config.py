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
CK_SHA256 = os.getenv("CK_SHA256")
CK_PATH = TOOLS_PATH / "ck" / CK_JAR_NAME

# 4B. RefactoringMiner Tool
RM_VERSION = os.getenv("RM_VERSION", "3.1.3")
RM_URL = os.getenv(
    "RM_URL",
    f"https://github.com/tsantalis/RefactoringMiner/releases/download/{RM_VERSION}/RefactoringMiner-{RM_VERSION}.zip"
)
RM_SHA256 = os.getenv("RM_SHA256")
RM_ENTRY_POINT_CLASS = "org.refactoringminer.RefactoringMiner"

if os.name == 'nt':
    RM_EXEC = "RefactoringMiner.bat"
else:
    RM_EXEC = "RefactoringMiner"
RM_PATH = TOOLS_PATH / f"RefactoringMiner-{RM_VERSION}" / "bin" / RM_EXEC

# --- 4D. EXECUTION LIMITS (large-repo safety for the full snapshot-grid run) ---
CK_TIMEOUT = int(os.getenv("CK_TIMEOUT", "3600"))     # seconds per snapshot
JAVA_XMX = os.getenv("JAVA_XMX", "4g")              # CK heap; QuestDB needs headroom

# --- 5. TARGET REPOSITORIES & INTERNAL ASSETS ---
RULES_DIR = REPO_ROOT / "pipeline" / "rulesets"

# --- 5B. RELEASE GRID ARTIFACTS ---
# Produced by rel_tag_mining_v3.ipynb, consumed by the mining adapters.
#
# These are GRID artifacts, not tool outputs. They describe which snapshots exist and which
# commits define them, so they live in VERSIONS_PATH together. OUTPUTS_PATH is reserved for
# what the adapters themselves write (JSONL, logs, batch state).
#
# The admission thresholds, cutoff and trigger window are NOT duplicated here on purpose:
# the notebook is the single source of truth and records them inside each manifest under
# "admission_thresholds". Read them from the manifest rather than re-declaring them, or the
# two will silently drift apart.
GRID_PATH = VERSIONS_PATH


def universe_file(repo_name: str) -> Path:
    """
    HEAD + the admitted near-mainline snapshot SHAs that the mining adapters must walk.

    Both LedgerAdapter and RefactoringMinerAdapter resolve their commit universe through
    this one function. Walking HEAD alone makes RefactoringMiner report zero refactorings
    for every off-mainline snapshot; walking --all pollutes with abandoned pull requests.
    """
    return GRID_PATH / f"adapter_universe_{repo_name}.json"


def rel_hist_file(repo_name: str) -> Path:
    """The frozen snapshot grid: the observation points for the study."""
    return GRID_PATH / f"rel_hist_{repo_name}.json"


def release_manifest_file(repo_name: str) -> Path:
    """Full mining record: admission thresholds, rejected tags, SHA aliases, grid rule."""
    return GRID_PATH / f"{repo_name}_release_manifest.json"

# --- 6. UTILITIES ---
def escape_path(path_obj):
    return str(path_obj).replace(" ", "\\\\ ")

CK_PATH_ESCAPED = escape_path(CK_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
WORKSPACE_ROOT_ESCAPED = escape_path(WORKSPACE_ROOT)

# --- 7. CONSTANTS ---
# One miner per run. No "all" -- each stage is invoked standalone. CK is the structural tool
# (PMD removed). "report" is a read-only universe verification over mined outputs.
VALID_STAGES = ["meta", "ledger", "refm", "ck", "report"]

# --- 8. I/O RESILIENCE CONFIGURATION ---
IO_MAX_RETRIES = int(os.getenv("IO_MAX_RETRIES", "5"))
IO_RETRY_DELAY_BASE = float(os.getenv("IO_RETRY_DELAY_BASE", "0.1"))