import subprocess
import os
from pathlib import Path
from typing import List, Tuple, Optional


def run_command(
        command: List[str],
        cwd: Optional[str] = None,
        allowed_exit_codes: List[int] = [0],
        log_file_path: Optional[Path] = None,
        verbose: bool = True  # [NEW] Flag to silence console output
) -> Tuple[bool, str]:
    """
    Executes a shell command safely.

    Args:
        command (list): The command to run.
        cwd (str): Working directory.
        allowed_exit_codes (list): Codes considered 'Success' (e.g., [0, 4] for PMD).
        log_file_path (Path): If provided, writes stdout/stderr to this file
                              instead of capturing it in memory.
        verbose (bool): If True, prints [EXEC] and errors to console.
                        If False, runs silently (useful for loops).

    Returns:
        tuple: (success (bool), output_summary (str))
    """
    cmd_str = " ".join(command)

    # [LOGIC] Only print to console if verbose is True
    if verbose:
        print(f"   [EXEC]: {cmd_str}")

    try:
        if log_file_path:
            # OPTION A: Stream to File (Silent Mode via File)
            # We open the file and let the subprocess write to it directly
            with open(log_file_path, "w") as f:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,  # Merge stderr into stdout
                    text=True,
                    check=False
                )
            # Output summary is just the path to the log
            output_content = f"Log saved to {log_file_path.name}"
        else:
            # OPTION B: Capture to Memory (Verbose/Default)
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            output_content = result.stdout.strip() + "\n" + result.stderr.strip()

        exit_code = result.returncode

        if exit_code in allowed_exit_codes:
            return True, output_content
        else:
            if verbose:
                print(f"❌ Command Failed (Exit Code {exit_code})")

            # If we logged to a file, print the last 10 lines for immediate context
            if log_file_path and log_file_path.exists() and verbose:
                print(f"   Last 10 lines of log ({log_file_path.name}):")
                try:
                    subprocess.run(
                        ["tail", "-n", "10", str(log_file_path)],
                        check=False
                    )
                except Exception as e:
                    print(f"   (Could not read log tail: {e})")

            return False, output_content

    except FileNotFoundError:
        if verbose:
            print(f"❌ Executable not found: {command[0]}")
        return False, "Command not found"
    except Exception as e:
        if verbose:
            print(f"❌ Unexpected Error: {e}")
        return False, str(e)