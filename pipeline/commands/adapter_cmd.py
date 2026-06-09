from pipeline.commands.i_commands import IPipelineCommand
from pipeline.adapters.i_adapters import IAdapter


class RunToolCommand(IPipelineCommand):
    """
    Concrete Command.
    Wraps a ToolAdapter (Receiver) and triggers its execution.
    """

    def __init__(self, adapter: IAdapter):
        # Store the Receiver (Adapter) as a protected field
        self._adapter = adapter

    def execute(self) -> bool:
        print(f"\n🚀 COMMAND: Executing {self._adapter.get_tool_name()}...")
        success = self._adapter.execute()  # [FIX] Delegate directly to IAdapter.execute()

        if success:
            print(f"✅ COMMAND: {self._adapter.get_tool_name()} finished successfully.")
            return True
        else:
            print(f"❌ COMMAND: {self._adapter.get_tool_name()} failed.")
            return False

    def get_tool_name(self) -> str:
        # [FIX] Use correct attribute name 'self._adapter'
        return self._adapter.get_tool_name()