import os
import urllib.request
import hashlib
import tempfile
from pathlib import Path

# Load config to get the URLs
from pipeline import config


def calculate_remote_hash(url: str, tool_name: str):
    print(f"\n🌐 Fetching {tool_name} from: {url}")

    # Use a secure temporary directory so we don't pollute the workspace
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = Path(temp_dir) / "downloaded_artifact"

        try:
            print("   ⬇️ Downloading...")
            urllib.request.urlretrieve(url, temp_file)

            print("   🧮 Calculating SHA-256...")
            sha256_hash = hashlib.sha256()
            with open(temp_file, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            final_hash = sha256_hash.hexdigest()
            print(f"   ✅ {tool_name.upper()}_SHA256={final_hash}")
            return final_hash

        except Exception as e:
            print(f"   ❌ Failed to process {tool_name}: {e}")
            return None


def main():
    print("--- 🔐 Smell-Ranker Hash Generator ---")
    print("Use these values to update your .env file.")

    calculate_remote_hash(config.CK_URL, "CK")
    calculate_remote_hash(config.RM_URL, "RM")
    calculate_remote_hash(config.PMD_URL, "PMD")

    print("\n⚠️  SECURITY REMINDER: Only run this script if you trust the current state of the remote URLs.")


if __name__ == "__main__":
    main()