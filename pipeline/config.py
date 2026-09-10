import os
from pathlib import Path
from typing import List

# --- 0. LOAD DOTENV ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# --- 1. ROOT DISCOVERY ---------------------------------------------------------------
#
# WHY THIS NO LONGER RAISES WHEN THERE IS NO .git
#
#   Walking up for a .git folder is right for a source checkout and wrong for an installed
#   package: `pip install quarry-msr` puts this file in site-packages, where no ancestor
#   directory has a .git and the old code raised RuntimeError at IMPORT time. The tool became
#   uninstallable the moment it was installed, and the failure appeared as an exception during
#   `import pipeline` rather than as anything a user could act on.
#
#   The fallback is the current working directory, which is where an installed tool should look
#   for a workspace anyway. QUARRY_HOME overrides both.

def _discover_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    while candidate != candidate.parent:
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    # Installed rather than checked out. Not an error.
    return Path.cwd()


REPO_ROOT = _discover_repo_root()


# --- 2. WORKSPACE ---------------------------------------------------------------------
#
# QUARRY_HOME is the current name. SMELL_RANKER_HOME is still honoured so an existing .env and
# any machine already configured keeps working; it is read second, so the new name wins where
# both are set.

_env_home = (os.getenv("QUARRY_HOME") or os.getenv("SMELL_RANKER_HOME") or "").strip()
_LEGACY_HOME_USED = bool(_env_home) and not (os.getenv("QUARRY_HOME") or "").strip()

if _env_home:
    WORKSPACE_ROOT = Path(_env_home)
else:
    WORKSPACE_ROOT = REPO_ROOT / "workspace_data"


# --- 3. CORE PATHS --------------------------------------------------------------------

TOOLS_PATH = WORKSPACE_ROOT / "tools"
REPOS_PATH = WORKSPACE_ROOT / "repos"
OUTPUTS_PATH = WORKSPACE_ROOT / "outputs"
VERSIONS_PATH = WORKSPACE_ROOT / "versions"

# parents=True: WORKSPACE_ROOT itself may not exist yet when QUARRY_HOME points somewhere new,
# and mkdir(exist_ok=True) alone fails with FileNotFoundError rather than creating the chain.
for _path in (WORKSPACE_ROOT, TOOLS_PATH, REPOS_PATH, OUTPUTS_PATH, VERSIONS_PATH):
    _path.mkdir(parents=True, exist_ok=True)


# --- 3B. WHERE THE WORKSPACE IS, AS DATA RATHER THAN AS A SIDE EFFECT ------------------

def describe() -> List[str]:
    """
    The workspace banner, returned instead of printed.

    IMPORTING A MODULE SHOULD NOT WRITE TO STDOUT. This block used to print four lines at
    import time, which meant `--help` opened with them, every rejected command line printed
    them before its error, every notebook cell that touched config emitted them, and -- because
    one of them carried an emoji -- a redirected run died inside an import, before argparse had
    seen a single argument.

    The caller decides when a run is real enough to deserve a banner; RunPlan.announce() does.
    """
    lines = [f"📂 Codebase Root: {REPO_ROOT}"]
    if _env_home:
        var = "SMELL_RANKER_HOME" if _LEGACY_HOME_USED else "QUARRY_HOME"
        lines.append(f"⚙️  Custom workspace from {var}")
        if _LEGACY_HOME_USED:
            lines.append("   (SMELL_RANKER_HOME is the old name; rename it to QUARRY_HOME)")
    else:
        lines.append("💻 Default workspace (no QUARRY_HOME set).")
    lines.append(f"📂 Workspace Root: {WORKSPACE_ROOT}")
    return lines


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
#
# Package-relative, NOT REPO_ROOT-relative. Rulesets ship inside the package, so their location
# is fixed relative to this file whether the package is a checkout or an installed wheel;
# deriving it from the project root breaks the moment there is no project root.
RULES_DIR = Path(__file__).resolve().parent / "rulesets"

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
#
# NOTE: pipeline/cli/spec.py is now the authoritative list -- it declares each stage together
# with the flags that stage accepts, and the CLI reads its choices from there. This constant is
# kept for anything still importing it, and must stay in step with STAGES.
VALID_STAGES = ["meta", "ledger", "refm", "ck", "channel", "report"]

# --- 7B. TRIGGER CHANNEL PLATFORMS ---
# A channel is one source of developer discourse. The git platform reads the local clone; the
# github platform needs an API token, which lives in .env and is never committed or logged.
CHANNEL_PLATFORMS = {
    "git":    ["commits"],
    "github": ["issues", "prs", "pr_reviews", "comments"],
}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API = os.getenv("GITHUB_API", "https://api.github.com")


def channel_file(platform: str, channel: str, repo_name: str) -> Path:
    """Mined channel records: one file per repo per channel."""
    return OUTPUTS_PATH / f"channel_{platform}_{channel}_{repo_name}.jsonl"


# --- 8. I/O RESILIENCE CONFIGURATION ---
IO_MAX_RETRIES = int(os.getenv("IO_MAX_RETRIES", "5"))
IO_RETRY_DELAY_BASE = float(os.getenv("IO_RETRY_DELAY_BASE", "0.1"))