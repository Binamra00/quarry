from pipeline.commands.i_commands import IPipelineCommand
from pipeline.metrics.temp_mets import BaseMetrics


class RunReportCommand(IPipelineCommand):
    """
    Concrete Command wrapping a BaseMetrics report (the Receiver).

    WHY A REPORT IS A COMMAND

        Reports used to run after the command loop, each in its own try/except, reached by a
        `if args.stage == "refm"` in the entry point. That gave them three things they should
        not have had: a second execution path, a private definition of failure, and immunity
        from the pipeline's health tracking -- a report that threw printed a warning and the
        run still exited 0.

        As commands they queue alongside the miners, and the runner's existing failure handling
        applies unchanged.

    THIS IS A CONSUMER

        It reads the miners' output rather than producing any, so it must not run after they
        have failed: summarising a truncated file produces a report indistinguishable from a
        real one. requires_healthy_pipeline tells the runner to skip it instead.

    BEHAVIOUR CHANGE WORTH KNOWING

        A failing report now makes the run exit non-zero. It previously printed a warning and
        exited 0, which meant a broken report was invisible to anything scripted.
    """

    def __init__(self, metrics: BaseMetrics):
        self._metrics = metrics

    @property
    def requires_healthy_pipeline(self) -> bool:
        return True

    def execute(self) -> bool:
        name = self.get_tool_name()
        print(f"\n📊 COMMAND: Generating {name}...")
        try:
            # run_report() is a Template Method returning None; success is the absence of an
            # exception. It handles "no input data" itself by printing and returning early,
            # which is a legitimate outcome rather than a failure.
            self._metrics.run_report()
        except Exception as e:
            print(f"❌ COMMAND: {name} failed: {type(e).__name__}: {e}")
            return False
        print(f"✅ COMMAND: {name} finished successfully.")
        return True

    def get_tool_name(self) -> str:
        return self._metrics.get_tool_name()
