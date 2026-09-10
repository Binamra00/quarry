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
        ...

    @abstractmethod
    def get_tool_name(self) -> str:
        """
        Returns the name of the tool/command for logging.
        """
        ...

    @property
    def requires_healthy_pipeline(self) -> bool:
        """
        Whether this command CONSUMES the output of earlier ones.

        A producer (a miner) is independent: it should still run after something else failed,
        because its own output is worth having. A consumer (a report) is not: it would read a
        file that another command left half written and summarise it as though it were
        complete, which is worse than producing nothing.

        Concrete with a default of False, deliberately -- every existing command is a producer,
        and making this abstract would break them all to state something none of them needed
        to say.
        """
        return False