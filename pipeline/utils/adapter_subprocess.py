import subprocess
import os
from pathlib import Path
from typing import List, Tuple, Optional


def run_command(
        command: List[str],
        cwd: Optional[str] = None,
        allowed_exit_codes: Optional[List[int]] = None,  # [FIX] Removed mutable default
        log_file_path: Optional[Path] = None,
        verbose: bool = True,
        timeout: int = 600  # [FIX] Added default timeout (10 minutes)
) -> Tuple[bool, str]:
    """
    Executes a shell command safely with timeouts and atomic logging.

    Args:
        command: The command arguments.
        cwd: Current working directory.
        allowed_exit_codes: List of return codes considered successful.
        log_file_path: Path to write stdout/stderr to (bypass memory).
        verbose: Whether to print to console.
        timeout: Max execution time in seconds.

    Returns:
        (success, output_content)
    """
    # [FIX] Handle mutable default argument
    if allowed_exit_codes is None:
        allowed_exit_codes = [0]

    cmd_str = " ".join(command)

    if verbose:
        print(f"   [EXEC]: {cmd_str}")

    try:
        if log_file_path:
            # OPTION A: Stream to File (Silent Mode / Debug Log)
            # Use append mode 'a' to prevent overwriting previous logs in the same session
            with open(log_file_path, "a") as f:
                f.write(f"\n\n--- EXEC: {cmd_str} ---\n")
                f.flush()

                # [FIX] Added timeout
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout
                )
                output_content = f"Log saved to {log_file_path.name}"
        else:
            # OPTION B: Capture to Memory (Standard)
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout  # [FIX] Added timeout
            )
            output_content = result.stdout.strip() + "\n" + result.stderr.strip()

        exit_code = result.returncode

        if exit_code in allowed_exit_codes:
            return True, output_content
        else:
            if verbose:
                print(f"❌ Command Failed (Exit Code {exit_code})")
            return False, output_content

    except subprocess.TimeoutExpired:
        msg = f"❌ Command timed out after {timeout} seconds: {command[0]}"
        if verbose:
            print(msg)
        # Log the timeout event to the file if one was provided
        if log_file_path:
            with open(log_file_path, "a") as f:
                f.write(f"\n{msg}\n")
        return False, "TIMEOUT"

    except FileNotFoundError:
        if verbose:
            print(f"❌ Executable not found: {command[0]}")
        return False, "Command not found"

    except Exception as e:
        if verbose:
            print(f"❌ Unexpected Error: {e}")
        return False, str(e)