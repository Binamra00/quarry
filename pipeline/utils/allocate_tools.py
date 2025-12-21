import sys
from abc import ABC, abstractmethod


# --- 1. The Strategy Interface ---
class IDisplayStrategy(ABC):
    """
    Strategy Interface for Console UI.
    Allows swapping between Jupyter/Colab rich output and standard Terminal text.
    Follows the Strategy Pattern to eliminate repeated environment checks.
    """

    @abstractmethod
    def update_progress(self, current: int, total: int, prefix: str):
        pass

    @abstractmethod
    def clear_line(self):
        pass


# --- 2. Concrete Strategy: Jupyter/Colab ---
class ColabStrategy(IDisplayStrategy):
    """
    Implementation for Jupyter Notebooks / Google Colab.
    Uses IPython widgets or clear_output for smooth web-based rendering.
    """

    def __init__(self):
        # Lazy import to ensure we don't crash if IPython is missing
        try:
            from IPython.display import clear_output
            self._clear_output_func = clear_output
        except ImportError:
            self._clear_output_func = None

    def update_progress(self, current: int, total: int, prefix: str):
        message = f"{prefix} {current}/{total}..."
        if self._clear_output_func:
            # wait=True prevents flickering by waiting for new output before clearing
            self._clear_output_func(wait=True)
            print(message)
        else:
            # Fallback if IPython is missing despite detection
            print(message)

    def clear_line(self):
        if self._clear_output_func:
            self._clear_output_func(wait=True)


# --- 3. Concrete Strategy: Standard Terminal ---
class TerminalStrategy(IDisplayStrategy):
    """
    Implementation for Standard Linux/Unix Terminals.
    Uses Carriage Return (\r) to overwrite the current line in place.
    """

    def update_progress(self, current: int, total: int, prefix: str):
        message = f"{prefix} {current}/{total}..."
        # \r moves cursor to start of line, allowing overwrite
        sys.stdout.write(f"\r{message}")
        sys.stdout.flush()

    def clear_line(self):
        # Overwrite line with spaces, then return to start
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()


# --- 4. Context & Environment Detection (The Singleton) ---
# We determine the strategy ONCE at module load time.
if 'ipykernel' in sys.modules:
    _active_strategy = ColabStrategy()
else:
    _active_strategy = TerminalStrategy()


# --- 5. Public API (Delegates to Active Strategy) ---
def update_progress(current: int, total: int, prefix: str = "Processing"):
    """
    Updates the console with a progress message using the active display strategy.

    Args:
        current (int): Current item number.
        total (int): Total number of items.
        prefix (str): Text to show before the counter.
    """
    _active_strategy.update_progress(current, total, prefix)


def clear_line():
    """Clears the current line using the active display strategy."""
    _active_strategy.clear_line()