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


def verify_checksum(file_path: Path, expected_hash: str) -> bool:
    """
    Calculate the SHA-256 checksum of ``file_path`` and compare it to
    ``expected_hash``.

    The ``expected_hash`` must be the full SHA-256 digest encoded as a
    lowercase hexadecimal string.
    """
    # [FIX] Validate Hash Format
    if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
        report(f"❌ Invalid expected SHA-256 hash format: {expected_hash}")
        return False

    if not file_path.is_file():
        report(f"❌ File not found for checksum verification: {file_path}")
        return False

    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            # Read in 4K chunks to avoid memory issues
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
    except (FileNotFoundError, OSError):
        # [FIX] Handle race condition if file is deleted during read
        report(f"❌ File disappeared or unreadable during checksum verification: {file_path}")
        return False

    calculated_hash = sha256_hash.hexdigest()

    if calculated_hash != expected_hash:
        report(f"❌ SECURITY CRITICAL: Checksum Mismatch!")
        report(f"   File:       {file_path.name}")
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

    if final_path.exists():
        report(f"✅ Found version: {target_folder_name}. Skipping download.")
        return True

    report(f"⬇️ Downloading {target_folder_name} from {url}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        report(f"❌ Download failed: {e}")
        return False

    # Security Checkpoint
    if not verify_checksum(zip_path, expected_hash):
        report(f"⛔ Aborting installation of '{target_folder_name}' due to security risk.")
        zip_path.unlink(missing_ok=True)
        return False

    report(f"📦 Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # [FIX] Robust Zip Root Detection
            namelist = zip_ref.namelist()
            if not namelist:
                raise ValueError("Downloaded zip archive is empty.")

            first_entry = namelist[0]
            parts = first_entry.split("/")
            if not parts or not parts[0]:
                raise ValueError(f"Could not determine top-level directory: {first_entry}")

            zip_root = parts[0]
            zip_ref.extractall(dest_dir)

        zip_path.unlink(missing_ok=True)

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

    # [FIX] Catch specific exceptions
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        report(f"❌ Extraction failed: {e}")
        zip_path.unlink(missing_ok=True)
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

    # 3. Fix Permissions
    if success_pmd and success_rm:
        make_executable(config.PMD_PATH)
        make_executable(config.RM_PATH)
        print("--- Toolchain Ready ---\n")
    else:
        raise RuntimeError("Toolchain provisioning failed due to download or security errors.")


if __name__ == "__main__":
    try:
        provision()
    except RuntimeError as e:
        print(f"❌ {e}")
        exit(1)