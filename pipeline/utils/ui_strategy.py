import sys


def update_progress(current: int, total: int, prefix: str = "Processing"):
    """
    Updates the console with a progress message.
    Automatically detects if running in Jupyter/Colab or a standard terminal.

    Args:
        current (int): Current item number.
        total (int): Total number of items.
        prefix (str): Text to show before the counter.
    """
    message = f"{prefix} {current}/{total}..."

    # Check if we are in a Jupyter/Colab environment
    is_notebook = 'ipykernel' in sys.modules

    if is_notebook:
        # SAFE IMPORT: Only import IPython if we are actually in a notebook
        try:
            from IPython.display import clear_output
            clear_output(wait=True)
            print(message)
        except ImportError:
            # Fallback if detection failed but module is missing
            print(message)
    else:
        # Standard Terminal: Use carriage return (\r) to overwrite line
        sys.stdout.write(f"\r{message}")
        sys.stdout.flush()


def clear_line():
    """Clears the current line (useful for cleanup after loops)."""
    is_notebook = 'ipykernel' in sys.modules

    if is_notebook:
        from IPython.display import clear_output
        clear_output(wait=True)
    else:
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()