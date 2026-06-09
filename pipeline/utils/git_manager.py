import subprocess
import sys
from pathlib import Path

class GitManager:
    @staticmethod
    def clone_with_progress(repo_url: str, dest_dir: Path) -> bool:
        """
        Clones a Git repository while streaming the live progress to the console.
        """
        print(f"   ☁️  Cloning remote repository: {repo_url}")
        print(f"       Destination: {dest_dir.name}\n")

        # The '--progress' flag forces Git to output its loading bar.
        # Keep excellent credential deadlock protections.
        cmd = [
            "git",
            "-c", "core.terminalprompt=false",
            "-c", "credential.helper=",
            "clone",
            "--progress",
            "--",
            repo_url,
            str(dest_dir)
        ]

        try:
            # Popen allows us to read the output stream live
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Git writes progress to stderr
                universal_newlines=True,
                bufsize=1
            )

            # Stream the output live to the console
            for line in process.stderr:
                # \r sends the cursor back to the start of the line to overwrite it
                sys.stdout.write(f"\r   ⏳ {line.strip():<80}")
                sys.stdout.flush()

            process.wait()

            # Clear the loading line once finished
            sys.stdout.write("\r" + " " * 85 + "\r")

            if process.returncode == 0:
                print(f"   ✅ Clone successful.")
                return True
            else:
                print(f"\n   ❌ Git clone failed. Return code: {process.returncode}")
                return False

        except Exception as e:
            print(f"\n   ❌ Critical error during clone: {e}")
            return False