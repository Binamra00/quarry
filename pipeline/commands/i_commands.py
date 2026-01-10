from abc import ABC, abstractmethod

class IPipelineCommand(ABC):
    """
    The Command Interface.
    Declares a method for executing a command.
    """

    @abstractmethod
    def execute(self) -> bool:
        """
        Execute the command logic.
        Returns True if successful, False otherwise.
        """
        pass