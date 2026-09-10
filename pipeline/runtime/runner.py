"""
Runs a list of commands and decides the exit code.

CIRCUIT BREAKER, NOT FAIL-FAST

    A failing command does NOT abort the run. Several adapters can be queued in one invocation
    -- `--channel issues,prs` is two, each with its own resumable state -- and an exhausted
    GitHub quota on the first is no reason to deny the second its chance to make progress.
    Everything independent still runs; the exit code is what carries the failure.

CONSUMERS ARE SKIPPED WHEN THE PIPELINE IS UNHEALTHY

    A report reads what the miners produced. Running one after its miner failed produces a
    summary of a partial file that looks exactly like a summary of a complete one, which is
    worse than no summary at all. Commands that declare requires_healthy_pipeline are skipped
    once anything has failed.

EXIT CODE

    Non-zero if ANY command failed, so a scripted or scheduled run cannot mistake a partial
    mine for a complete one.
"""

from typing import Dict, List

from pipeline.commands.i_commands import IPipelineCommand


class PipelineRunner:

    def __init__(self, commands: List[IPipelineCommand]):
        self.commands = commands
        self.results: Dict[str, bool] = {}
        self.healthy = True

    def run(self) -> int:
        if not self.commands:
            print("\n⚠️  Nothing to run for this stage.")
            return 0

        for command in self.commands:
            name = command.get_tool_name()

            if command.requires_healthy_pipeline and not self.healthy:
                print(f"\n⛔ Skipping {name}: an earlier stage failed, so it would summarise "
                      f"a partial result.")
                self.results[name] = False
                continue

            success = command.execute()
            self.results[name] = success

            if not success:
                print(f"⚠️ {name} failed or was interrupted. Marking pipeline as UNHEALTHY.")
                self.healthy = False

        return self._finalize()

    def _finalize(self) -> int:
        if not self.healthy:
            print("\n❌ Pipeline completed with errors.")
            print("Execution Summary:", self.results)
            return 1

        print("\n--- 🏁 Pipeline Completion Report ---")
        print("\n✅ SUCCESS: Pipeline finished successfully.")
        return 0
