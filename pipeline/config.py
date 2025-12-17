# This file holds all configuration, paths, and settings for our pipeline.
# It is imported by main.py and other modules.

from pathlib import Path

# --- 1. DEFINE CORE PATHS ---
# These paths point to locations inside your Google Drive structure
# We use Path objects for robust cross-platform compatibility
DRIVE_PATH = Path("/content/drive/My Drive/Thesis Project")
TOOLS_PATH = DRIVE_PATH / "tools"
REPOS_PATH = DRIVE_PATH / "repos"
OUTPUTS_PATH = DRIVE_PATH / "outputs"

# --- 2. DEFINE TOOL EXECUTABLES ---
PMD_PATH = TOOLS_PATH / "pmd-bin-7.18.0" / "bin" / "pmd"
RM_PATH = TOOLS_PATH / "RefactoringMiner_v3" / "bin" / "RefactoringMiner"

# --- 3. DEFINE TOY PROJECT ---
# This is the variable your repo_mets.py script is looking for!
TOY_PROJECT_PATH = REPOS_PATH / "toy_project"

# --- 4. ESCAPED PATHS (FOR SHELL EXECUTION) ---
def escape_path(path_obj):
    """Escapes a pathlib.Path object for safe use in a shell command."""
    return str(path_obj).replace(" ", "\\ ")

PMD_PATH_ESCAPED = escape_path(PMD_PATH)
RM_PATH_ESCAPED = escape_path(RM_PATH)
TOY_PROJECT_PATH_ESCAPED = escape_path(TOY_PROJECT_PATH)

# --- 5. EXECUTION SETTINGS ---
PMD_DESIGN_RULESET = "rulesets/java/pmd_rulset.xml"