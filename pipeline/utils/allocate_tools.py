import os
import shutil
import stat
import urllib.request
import zipfile
import hashlib
from pathlib import Path
from pipeline import config


def report(msg):
    print(f"   [Toolchain] {msg}")


def verify_checksum(file_path, expected_hash):
    """
    Calculates SHA-256 of the file and compares with expected_hash.
    Returns True if match or if expected_hash is a placeholder.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in 4K chunks to avoid memory issues
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    calculated_hash = sha256_hash.hexdigest()

    # TOFU (Trust On First Use) helper for the developer
    if "REPLACE_WITH" in expected_hash:
        report(f"⚠️  SECURITY NOTICE: Hash validation pending.")
        report(f"   Calculated Hash for {file_path.name}: {calculated_hash}")
        report(f"   ACTION: Copy this hash into config.py to lock the supply chain.")
        return True  # Allow pass for setup, but warn

    if calculated_hash != expected_hash:
        report(f"❌ SECURITY CRITICAL: Checksum Mismatch!")
        report(f"   Expected:   {expected_hash}")
        report(f"   Calculated: {calculated_hash}")
        return False

    report(f"🔒 Checksum Verified: {calculated_hash[:8]}...")
    return True


def download_and_extract(url, target_folder_name, expected_hash):
    """
    Downloads a zip, VERIFIES HASH, and extracts it.
    Renames the extracted folder to 'target_folder_name'.
    """
    dest_dir = config.TOOLS_PATH
    zip_path = dest_dir / "temp_tool.zip"
    final_path = dest_dir / target_folder_name

    # If the specific version folder exists, we are done.
    if final_path.exists():
        # Echo the version being used
        report(f"✅ Found version: {target_folder_name}. Skipping download.")
        return True

    report(f"⬇️ Downloading {target_folder_name} from {url}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        report(f"❌ Download failed: {e}")
        return False

    # [NEW] Security Checkpoint
    if not verify_checksum(zip_path, expected_hash):
        report("⛔ Aborting installation due to security risk.")
        if zip_path.exists():
            zip_path.unlink()  # Delete the compromised file
        return False

    report(f"📦 Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # We need to know the top-level folder inside the zip to rename it
            zip_root = zip_ref.namelist()[0].split('/')[0]
            zip_ref.extractall(dest_dir)

        # Cleanup zip
        zip_path.unlink()

        # Rename the extracted folder to our target version name
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
        if zip_path.exists():
            zip_path.unlink()
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
    success_pmd = download_and_extract(config.PMD_URL, config.PMD_VERSION, config.PMD_SHA256)

    # 2. Check & Install RefactoringMiner
    success_rm = download_and_extract(config.RM_URL, config.RM_VERSION, config.RM_SHA256)

    # 3. Fix Permissions (Only if downloads/checks succeeded)
    if success_pmd and success_rm:
        make_executable(config.PMD_PATH)
        make_executable(config.RM_PATH)
        print("--- Toolchain Ready ---\n")
    else:
        print("❌ Toolchain provisioning failed.")
        exit(1)


if __name__ == "__main__":
    provision()