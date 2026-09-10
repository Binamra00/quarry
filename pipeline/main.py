"""
Entry point.

Six steps, no decisions. Everything this used to do -- flag validation, warning banners,
toolchain provisioning, repository acquisition, sampler resolution, command assembly, the
execution loop, post-run reporting -- now belongs to a module that can be tested and reused
without a terminal attached.

    CliParser        argv            -> RunPlan
    StageValidator   RunPlan         -> RunPlan (validated, paths resolved)
    Workspace        RunPlan         -> a repository ready to mine
    PipelineFactory  (plan, repo)    -> the commands that plan implies
    PipelineRunner   commands        -> an exit code

Driving the pipeline from a notebook means building a RunPlan directly and skipping the first
step; nothing below it knows the command line exists.
"""

import sys

from pipeline.cli.parser import CliParser
from pipeline.cli.validate import StageValidator, CliError
from pipeline.factories.adapter_fact import PipelineFactory
from pipeline.runtime.runner import PipelineRunner
from pipeline.runtime.workspace import Workspace, WorkspaceError


def main() -> int:
    try:
        plan = StageValidator().enforce(CliParser().parse())
    except CliError as e:
        e.report()
        return 1

    plan.announce()

    try:
        repo = Workspace.prepare(plan)
    except WorkspaceError as e:
        print(f"\n❌ {e}")
        return 1

    commands = PipelineFactory.create_commands(plan, repo)
    return PipelineRunner(commands).run()


if __name__ == "__main__":
    sys.exit(main())