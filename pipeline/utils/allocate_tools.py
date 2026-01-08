import os
import sys
import shutil
import stat
import urllib.request
import zipfile
import hashlib
from pathlib import Path
from typing import Set
from pipeline import config


def report(msg: str):
    print(f"   [Toolchain] {msg}")


def verify_checksum(file_path: Path, expected_hash: str) -> bool:
    """
    Calculate the SHA-256 checksum of ``file_path`` and compare it to
    ``expected_hash``.

    :param file_path: Path to the file to verify.
    :param expected_hash: The expected SHA-256 digest (64-char lowercase hex).
    :return: True if the file exists and checksum matches, False otherwise.
    """
    if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
        report(f"❌ Invalid configuration: expected_hash must be 64-char lowercase hex.")
        report(f"   Provided: {expected_hash}")
        return False

    if not file_path.is_file():
        report(f"❌ File not found for checksum verification: {file_path}")
        return False

    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
    except (FileNotFoundError, OSError):
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


def download_and_extract(url: str, target_folder_name: str, expected_hash: str) -> bool:
    """
    Download a ZIP archive, verify its integrity, and extract it safely.

    This function implements "Zip Slip" protection to prevent path traversal attacks.

    :param url: The URL to download the tool from.
    :param target_folder_name: The expected folder name in the workspace.
    :param expected_hash: The SHA-256 hash to verify the download (Supply Chain Security).
    :return: True if successful, False if any step fails.
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

    if not verify_checksum(zip_path, expected_hash):
        report(f"⛔ Aborting installation of '{target_folder_name}' due to security risk.")
        zip_path.unlink(missing_ok=True)
        return False

    report(f"📦 Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            safe_members = []
            top_levels: Set[str] = set()
            dest_dir_resolved = dest_dir.resolve()

            for member in zip_ref.infolist():
                if not member.filename:
                    continue

                # Check for Zip Slip (Path Traversal)
                member_path = Path(member.filename)
                target_path = (dest_dir_resolved / member_path).resolve()

                # [FIX] Robust Path Traversal Check using commonpath
                try:
                    common_path = os.path.commonpath([str(dest_dir_resolved), str(target_path)])
                except ValueError:
                    # Handles cases on Windows where drives differ (C: vs D:)
                    raise ValueError(f"Security: Zip entry '{member.filename}' extracts to different drive.")

                if str(common_path) != str(dest_dir_resolved):
                    raise ValueError(f"Security: Zip entry '{member.filename}' attempts path traversal.")

                safe_members.append(member)

                parts = member.filename.strip("/").split("/")
                if parts and parts[0]:
                    top_levels.add(parts[0])

            if not safe_members:
                # [FIX] Added context to error message
                raise ValueError(f"Downloaded zip from {url} is empty.")

            if len(top_levels) != 1:
                raise ValueError(
                    f"Archive for '{target_folder_name}' is malformed. "
                    f"Expected 1 top-level directory, found: {sorted(top_levels)}"
                )

            zip_root = next(iter(top_levels))
            zip_ref.extractall(dest_dir, members=safe_members)

        zip_path.unlink(missing_ok=True)
        extracted_path = dest_dir / zip_root

        if extracted_path != final_path:
            if final_path.exists():
                shutil.rmtree(final_path)

            if extracted_path.exists():
                extracted_path.rename(final_path)
            else:
                report(f"⚠️ Warning: Extracted folder '{zip_root}' missing after extraction.")
                return False

        report(f"✅ Installed: {final_path.name}")
        return True

    except (zipfile.BadZipFile, OSError, ValueError) as e:
        report(f"❌ Extraction failed: {e}")
        zip_path.unlink(missing_ok=True)
        return False


def make_executable(tool_path: Path):
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

    success_pmd = download_and_extract(config.PMD_URL, config.PMD_VERSION, config.PMD_SHA256)
    success_rm = download_and_extract(config.RM_URL, config.RM_VERSION, config.RM_SHA256)

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
        sys.exit(1)