# This module handles the execution of external shell commands.
# It is part of the 'utils' package.

import subprocess


def run_command(command, working_dir=None):
    """
    Executes a shell command and returns the result.

    Args:
        command (list): A list of strings representing the command and arguments.
                        Example: ["ls", "-la"]
        working_dir (str, optional): The directory to run the command in.

    Returns:
        tuple: (success (bool), output (str))
    """
    # Log the command we are about to run (joined by spaces for readability)
    print(f"[RUNNING]: {' '.join(command)}")

    try:
        # We use subprocess.run to execute the command.
        # check=True raises an error if the command fails (exit code != 0).
        # capture_output=True grabs stdout and stderr so we can use them.
        # text=True ensures the output is a string, not bytes.
        # shell=False is safer and avoids injection vulnerabilities.
        result = subprocess.run(
            command,
            cwd=working_dir,
            check=True,
            capture_output=True,
            text=True,
            shell=False
        )

        # If we get here, the command succeeded (exit code 0)
        print(f"[STDOUT]:\n{result.stdout}")

        # Some tools print warnings to stderr even on success, so we log it if present.
        if result.stderr:
            print(f"[STDERR]:\n{result.stderr}")

        return True, result.stdout

    except subprocess.CalledProcessError as e:
        # This block catches commands that ran but failed (exit code != 0)
        print(f"[ERROR]: Command failed with exit code {e.returncode}")
        print(f"[STDOUT]:\n{e.stdout}")
        print(f"[STDERR]:\n{e.stderr}")
        return False, e.stderr

    except FileNotFoundError:
        # This block catches cases where the executable itself doesn't exist
        print(f"[ERROR]: Command not found. Is the path correct?\n{command[0]}")
        return False, "Command not found."