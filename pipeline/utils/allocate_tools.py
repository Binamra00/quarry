import os
import shutil
import stat
import urllib.request
import zipfile
from pathlib import Path
from pipeline import config

# --- DOWNLOAD URLS ---
# [cite_start]Using the exact versions mentioned in your thesis logs [cite: 7, 20]
PMD_URL = "https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.18.0/pmd-dist-7.18.0-bin.zip"
RM_URL = "https://github.com/tsantalis/RefactoringMiner/releases/download/3.0/RefactoringMiner-3.0.zip"


def report(msg):
    print(f"   [Toolchain] {msg}")


def download_and_extract(url, target_name):
    """
    Downloads a zip file, extracts it, and renames the folder to match config.py.
    """
    dest_dir = config.TOOLS_PATH
    zip_path = dest_dir / "temp_tool.zip"
    final_path = dest_dir / target_name

    report(f"⬇️ Downloading {target_name}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        report(f"❌ Download failed: {e}")
        return False

    report(f"📦 Extracting to {dest_dir}...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dest_dir)

        # Cleanup zip
        zip_path.unlink()

        # --- HANDLING FOLDER RENAMES ---
        # PMD zip extracts to 'pmd-bin-7.18.0' (Matches config, no rename needed)
        # RefactoringMiner zip extracts to 'RefactoringMiner-3.0' (Needs rename to 'RefactoringMiner_v3')

        extracted_name = ""
        if "pmd" in target_name:
            extracted_name = "pmd-bin-7.18.0"
        elif "RefactoringMiner" in target_name:
            extracted_name = "RefactoringMiner-3.0"

        extracted_path = dest_dir / extracted_name

        if extracted_path.exists() and extracted_path != final_path:
            # If the folder exists from a previous bad run, remove it
            if final_path.exists():
                shutil.rmtree(final_path)
            extracted_path.rename(final_path)

        report(f"✅ Installed: {final_path.name}")
        return True

    except Exception as e:
        report(f"❌ Extraction failed: {e}")
        return False


def make_executable(path):
    """
    Equivalent to chmod +x
    """
    if path.exists():
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC)
        report(f"🔧 Permissions fixed: {path.name}")
    else:
        report(f"⚠️ Binary not found for permission fix: {path}")


def provision():
    print(f"\n--- 🛠️ Provisioning Analysis Toolchain ---")
    print(f"Target Directory: {config.TOOLS_PATH}")

    # 1. Check & Install PMD
    if config.PMD_PATH.exists():
        report(f"Found PMD ({config.PMD_VERSION}). Skipping download.")
    else:
        report(f"PMD missing. Installing...")
        download_and_extract(PMD_URL, config.PMD_VERSION)

    # 2. Check & Install RefactoringMiner
    if config.RM_PATH.exists():
        report(f"Found RefactoringMiner ({config.RM_VERSION}). Skipping download.")
    else:
        report(f"RefactoringMiner missing. Installing...")
        download_and_extract(RM_URL, config.RM_VERSION)

    # 3. Fix Permissions (Crucial for Linux/Colab)
    # PMD usually has a shell script 'pmd'
    make_executable(config.PMD_PATH)
    # RefactoringMiner has a script 'RefactoringMiner'
    make_executable(config.RM_PATH)

    print("--- Toolchain Ready ---\n")


if __name__ == "__main__":
    provision()