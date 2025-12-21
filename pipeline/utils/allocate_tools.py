import os
import shutil
import stat
import urllib.request
import zipfile
from pathlib import Path
from pipeline import config

# --- Base URLs ---
# PMD uses tags like: pmd_releases/7.18.0 (URL-encoded as pmd_releases%2F7.18.0)
PMD_BASE_URL = "https://github.com/pmd/pmd/releases/download"
RM_BASE_URL = "https://github.com/tsantalis/RefactoringMiner/releases/download"

# --- Dynamically Constructed URLs ---
PMD_URL = (
    f"{PMD_BASE_URL}/pmd_releases%2F{config.PMD_VERSION}/"
    f"pmd-dist-{config.PMD_VERSION}-bin.zip"
)

RM_URL = (
    f"{RM_BASE_URL}/{config.RM_VERSION}/"
    f"RefactoringMiner-{config.RM_VERSION}.zip"
)

def report(msg):
    print(f"   [Toolchain] {msg}")

def download_and_extract(url, target_folder_name):
    """
    Downloads a zip and extracts it.
    Renames the extracted folder to 'target_folder_name'.
    This allows multiple tool versions to coexist side-by-side.
    """
    dest_dir = config.TOOLS_PATH
    zip_path = dest_dir / "temp_tool.zip"
    final_path = dest_dir / target_folder_name

    # If the specific version folder exists, we are done.
    if final_path.exists():
        report(f"✅ Found version: {target_folder_name}. Skipping download.")
        return True

    report(f"⬇️ Downloading {target_folder_name} from {url}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        report(f"❌ Download failed: {e}")
        return False

    report(f"📦 Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_root = zip_ref.namelist()[0].split('/')[0]
            zip_ref.extractall(dest_dir)

        zip_path.unlink()

        extracted_path = dest_dir / zip_root

        if extracted_path != final_path:
            if final_path.exists():
                shutil.rmtree(final_path)

            if extracted_path.exists():
                extracted_path.rename(final_path)
            else:
                report(f"⚠️ Warning: Expected extracted folder {zip_root} not found.")

        report(f"✅ Installed: {final_path.name}")
        return True

    except Exception as e:
        report(f"❌ Extraction failed: {e}")
        return False

def make_executable(tool_path):
    """Equivalent to chmod +x"""
    if tool_path.exists():
        st = os.stat(tool_path)
        os.chmod(tool_path, st.st_mode | stat.S_IEXEC)
        report(f"🔧 Permissions fixed: {tool_path.name}")
    else:
        report(f"⚠️ Binary not found for permission fix: {tool_path}")

def provision():
    print(f"\n--- 🛠️ Provisioning Analysis Toolchain ---")
    print(f"Target Directory: {config.TOOLS_PATH}")

    # 1. Check & Install PMD
    download_and_extract(
        PMD_URL,
        f"pmd-{config.PMD_VERSION}"
    )

    # 2. Check & Install RefactoringMiner
    download_and_extract(
        RM_URL,
        f"RefactoringMiner-{config.RM_VERSION}"
    )

    # 3. Fix Permissions
    make_executable(config.PMD_PATH)
    make_executable(config.RM_PATH)

    print("--- Toolchain Ready ---\n")

if __name__ == "__main__":
    provision()
