import sys


def update_progress(current: int, total: int, prefix: str = "Processing"):
    """
    Updates the console with a standard CLI progress message using carriage returns.

    Args:
        current (int): Current item number.
        total (int): Total number of items.
        prefix (str): Text to show before the counter.
    """
    message = f"{prefix} {current}/{total}..."

    # Standard Terminal: Use carriage return (\r) to overwrite the current line
    # end='' prevents a newline, allowing the next update to overwrite this one
    sys.stdout.write(f"\r{message}")
    sys.stdout.flush()


def clear_line():
    """
    Clears the current console line.
    Useful for removing the final progress bar state before printing a new log.
    """
    # Overwrite the line with spaces, then return carriage to start
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()