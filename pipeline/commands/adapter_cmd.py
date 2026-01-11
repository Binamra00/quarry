from pipeline.commands.i_commands import IPipelineCommand
from pipeline.adapters.i_adapters import IAdapter


class RunToolCommand(IPipelineCommand):
    """
    Concrete Command.
    Wraps a ToolAdapter (Receiver) and triggers its execution.
    """

    def __init__(self, adapter: IAdapter):
        # We store the Receiver (Adapter) as a field
        self._adapter = adapter

    def execute(self) -> bool:
        print(f"\n🚀 COMMAND: Executing {self._adapter.get_tool_name()}...")

        # Delegate the actual work to the Receiver
        success = self._adapter.execute()

        if success:
            print(f"✅ COMMAND: {self._adapter.get_tool_name()} finished successfully.")
            return True
        else:
            print(f"❌ COMMAND: {self._adapter.get_tool_name()} failed.")
            return False

    def get_tool_name(self) -> str:
        # [FIX] Delegate to the adapter instead of hardcoding "MiningTools"
        return self.adapter.get_tool_name()