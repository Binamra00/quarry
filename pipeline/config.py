# This file holds all configuration, paths, and settings for our pipeline.
# It is imported by main.py and other modules.

from pathlib import Path

# --- 1. ROBUST PROJECT ROOT DISCOVERY (Best Practice) ---
# Instead of hardcoding depth (.parent.parent), we traverse up the directory tree
# until we find the ".git" folder. This allows config.py to live anywhere.
current_path = Path(__file__).resolve()
root_candidate = current_path.parent

while not (root_candidate / ".git").exists():
    if root_candidate == root_candidate.parent: # Hit filesystem root
        raise RuntimeError("❌ Could not find Project Root (no .git folder found).")
    root_candidate = root_candidate.parent

REPO_ROOT = root_candidate

# --- 2. DEFINE CORE PATHS ---
# These paths point to locations inside your Google Drive structure
DRIVE_PATH = Path("/content/drive/My Drive/Thesis Project")
TOOLS_PATH = DRIVE_PATH / "tools"
REPOS_PATH = DRIVE_PATH / "repos"
OUTPUTS_PATH = DRIVE_PATH / "outputs"

# --- 3. DEFINE TOOL EXECUTABLES ---
PMD_PATH = TOOLS_PATH / "pmd-bin-7.18.0" / "bin" / "pmd"
RM_PATH = TOOLS_PATH / "RefactoringMiner_v3" / "bin" / "RefactoringMiner"

# --- 4. DEFINE TOY PROJECT ---
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 5. RULESETS ---
# Updated to match your refactoring: pipeline/config/ -> pipeline/rulesets/
# Note: PMD requires an XML file.
PMD_RULESET_PATH = REPO_ROOT / "pipeline" / "rulesets" / "pmd_rule_00.xml"

# --- 6. UTILITIES ---
def escape_path(path_obj):
    """Escapes a pathlib.Path object for safe use in a shell command."""
    return str(path_obj).replace(" ", "\\ ")

PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)