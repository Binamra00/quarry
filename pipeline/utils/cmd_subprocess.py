import subprocess
from typing import List, Tuple, Optional


def run_command(command: List[str], cwd: Optional[str] = None, allowed_exit_codes: List[int] = [0]) -> Tuple[bool, str]:
    """
    Executes a shell command safely and returns the result.

    Args:
        command (list): The command to run (e.g., ["ls", "-la"]).
        cwd (str, optional): The directory to run the command in.
        allowed_exit_codes (list): Exit codes that are considered "Success". 
                                   Default is [0]. PMD uses [0, 4].

    Returns:
        tuple: (success (bool), output (str))
    """
    cmd_str = " ".join(command)
    print(f"   [EXEC]: {cmd_str}")

    try:
        # check=False allows us to manually handle the exit code
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        exit_code = result.returncode

        # Log output if verbose (optional, keeping it clean for now)
        # if stdout: print(f"   [STDOUT]: {stdout[:200]}...") 

        if exit_code in allowed_exit_codes:
            return True, stdout
        else:
            print(f"❌ Command Failed (Exit Code {exit_code})")
            print(f"   Command: {cmd_str}")
            if stderr:
                print(f"   [STDERR]: {stderr}")
            return False, stderr

    except FileNotFoundError:
        print(f"❌ Executable not found: {command[0]}")
        return False, "Command not found"
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False, str(e)