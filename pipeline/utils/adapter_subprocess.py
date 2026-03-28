import os
import signal
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional


def kill_process_tree(pid: int):
    """Cross-platform utility to brutally kill a process and all its child processes."""
    try:
        if sys.platform == 'win32':
            # Windows: /F (Force) /T (Tree) /PID (Process ID)
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # POSIX (Mac/Linux): Send SIGKILL to the entire process group
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception as e:
        print(f"⚠️ Warning: Failed to clean up process tree for PID {pid}: {e}")


def run_command(
        command: List[str],
        cwd: Optional[str] = None,
        allowed_exit_codes: Optional[List[int]] = None,
        log_file_path: Optional[Path] = None,
        verbose: bool = True,
        timeout: int = 600
) -> Tuple[bool, str]:
    """
    Executes a shell command safely with timeouts and atomic logging.

    Args:
        command: The command and its arguments as a list of strings.
        cwd: Optional working directory in which to execute the command.
        allowed_exit_codes: List of exit codes that are considered successful.
            Defaults to [0] if not provided.
        log_file_path: Optional path to a log file to which output is streamed.
        verbose: If True, prints execution details and error messages.
        timeout: Maximum time to wait for the command to complete, in seconds.
            Defaults to 600 seconds.

    Returns:
        A tuple (success, output) where success is True if the command
        completed with an allowed exit code, and output contains either
        captured output or a status/message string.
    """
    if allowed_exit_codes is None:
        allowed_exit_codes = [0]

    cmd_str = " ".join(command)

    if verbose:
        print(f"   [EXEC]: {cmd_str}")

    kwargs = {
        'cwd': cwd,
        'text': True,
        'encoding': 'utf-8',
        'errors': 'replace'
    }

    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True

    proc = None  # Initialize proc so the exception blocks can access it

    try:
        if log_file_path:
            # OPTION A: Stream to File (Silent Mode / Debug Log)
            # Use append mode 'a' to prevent overwriting previous logs
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n--- EXEC: {cmd_str} ---\n")
                f.flush()  # Ensure header is written before subprocess writes

                proc = subprocess.Popen(
                    command,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    **kwargs
                )

                # Block and wait for timeout
                proc.communicate(timeout=timeout)
                exit_code = proc.returncode

            # Assignment outdented outside the with block
            output_content = f"Log saved to {log_file_path.name}"
        else:
            # OPTION B: Capture to Memory (Standard)
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs
            )

            # Block and capture
            stdout, stderr = proc.communicate(timeout=timeout)
            output_content = (stdout or "").strip() + "\n" + (stderr or "").strip()
            exit_code = proc.returncode

        if exit_code in allowed_exit_codes:
            return True, output_content
        else:
            if verbose:
                print(f"❌ Command Failed (Exit Code {exit_code})")
            return False, output_content


    except subprocess.TimeoutExpired:

        msg = f"❌ Command timed out after {timeout} seconds: {command[0]}"

        # NUKE THE ZOMBIES
        if proc:
            kill_process_tree(proc.pid)

            # Reap the zombie pipes
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()

        if verbose:
            print(msg)
            print("   🧹 Executed Process Tree Cleanup & Reaped I/O Pipes.")

        if log_file_path:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"\n{msg}\n")
                f.write("🧹 Process Tree Cleanup & Pipe Reaping Executed.\n")

        return False, "TIMEOUT"

    except FileNotFoundError:
        if verbose:
            print(f"❌ Executable not found: {command[0]}")
        return False, "Command not found"


    except Exception as e:

        if verbose:
            print(f"❌ Unexpected Error: {e}")

        # Failsafe cleanup
        if proc:
            kill_process_tree(proc.pid)

            # Failsafe pipe reaping
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass

        return False, str(e)