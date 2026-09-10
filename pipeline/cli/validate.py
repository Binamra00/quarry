"""
Enforcement of the stage/flag table, plus the checks that cannot be expressed in it.

EVERY VIOLATION IS REPORTED, NOT JUST THE FIRST

    The old guards each ended in sys.exit(1), so a command line with three mistakes had to be
    run three times to learn them all. Violations are collected here and raised together.

IT RAISES RATHER THAN EXITS

    Exiting from deep inside a validator makes the rules untestable and unusable from anything
    that is not a terminal. CliError carries the messages; the entry point decides that a CLI
    failure means exit code 1.

WHAT IS NOT IN THE TABLE

    Three rules are about the VALUES of flags rather than their presence, so they live here as
    named methods:

      - a channel name must be one the platform declares
      - --universe is meaningless on a non-git channel, because issues are not commits
      - a file-valued flag must point at a file that exists

    Each is a single readable check. Generalising them into the table would mean inventing a
    rule language to express three rules.
"""

import sys
from pathlib import Path
from typing import List, Optional

from pipeline import config
from pipeline.cli import spec
from pipeline.cli.plan import RunPlan


class CliError(Exception):
    """One or more invalid combinations of command-line flags."""

    def __init__(self, messages: List[str]):
        self.messages = messages
        super().__init__("\n".join(messages))

    def report(self) -> None:
        for m in self.messages:
            print(f"\n❌ {m}")


class StageValidator:
    def __init__(self, stages=None):
        self.stages = stages or spec.STAGES

    # ------------------------------------------------------------------ entry point

    def enforce(self, plan: RunPlan) -> RunPlan:
        """
        Check `plan` against the table. Returns a plan with file paths resolved.

        Raises CliError listing everything that is wrong.
        """
        errors: List[str] = []

        if plan.stage not in self.stages:
            raise CliError([f"Unknown stage '{plan.stage}'. "
                            f"Available: {', '.join(self.stages)}"])

        errors += self._check_allowed(plan)
        errors += self._check_required(plan)
        errors += self._check_mutually_exclusive(plan)
        errors += self._check_universe_declared(plan)
        errors += self._check_channels(plan)

        universe_path = sample_path = None
        if not errors:
            # Only look for files once the flags themselves make sense; otherwise a stage
            # mismatch and a missing file are reported together and the second is noise.
            universe_path, sample_path, file_errors = self._resolve_files(plan)
            errors += file_errors

        if errors:
            raise CliError(errors)

        return plan.with_paths(universe_path, sample_path)

    # ------------------------------------------------------------------ table-driven checks

    def _check_allowed(self, plan: RunPlan) -> List[str]:
        out = []
        for flag in sorted(plan.given_flags - plan.spec.allows):
            owners = spec.stages_allowing(flag)
            where = ", ".join(owners) if owners else "no stage"
            out.append(f"'--{flag}' is not valid for stage '{plan.stage}'.\n"
                       f"   It applies to: {where}.")
        return out

    def _check_required(self, plan: RunPlan) -> List[str]:
        out = []
        for flag in sorted(plan.spec.requires - plan.given_flags):
            hint = ""
            if flag == spec.PLATFORM:
                hint = f"\n   Available: {', '.join(config.CHANNEL_PLATFORMS)}."
            elif flag == spec.CHANNEL and plan.known_channels:
                hint = (f"\n   Available for '{plan.platform}': "
                        f"{', '.join(plan.known_channels)}, or 'all'.")
            out.append(f"Stage '{plan.stage}' requires '--{flag}'.{hint}")
        return out

    @staticmethod
    def _check_mutually_exclusive(plan: RunPlan) -> List[str]:
        given = plan.given_flags
        return [f"'--{a}' and '--{b}' are mutually exclusive.\n   {why}"
                for a, b, why in spec.MUTUALLY_EXCLUSIVE
                if a in given and b in given]

    @staticmethod
    def _check_universe_declared(plan: RunPlan) -> List[str]:
        """
        A stage that walks commits must say WHICH commits. There is no default.

        An unstated universe is how outputs silently stop joining: the run succeeds, the
        records look fine, and they simply never match the ones mined against the grid.
        """
        given = plan.given_flags
        chose_one = (spec.UNIVERSE in given) or (spec.FULL in given)

        if plan.walks_commits and not chose_one and spec.VERSION not in given:
            return [f"'{plan.stage}' walks commits, so it must be told which ones.\n"
                    f"   --universe FILE   mine the pinned study grid (what every other "
                    f"miner used)\n"
                    f"   --full            mine the whole repository (--all)\n"
                    f"\n   There is no default: an unstated universe is how outputs silently "
                    f"stop joining."]

        # Guarded on `allows`: a stage that does not accept --full at all was already reported
        # by _check_allowed, and saying it twice is noise. This branch is for the stage that
        # DOES accept it but not in this configuration -- a channel on the github platform.
        if spec.FULL in given and spec.FULL in plan.spec.allows and not plan.walks_commits:
            reason = ("The github platform reads an API, not commit history."
                      if plan.stage == "channel"
                      else f"Stage '{plan.stage}' does not walk commit history.")
            return [f"'--full' is not valid here.\n   {reason}"]

        return []

    # ------------------------------------------------------------------ value checks

    @staticmethod
    def _check_channels(plan: RunPlan) -> List[str]:
        if plan.stage != "channel":
            return []

        out = []
        if plan.platform and plan.platform_key not in config.CHANNEL_PLATFORMS:
            out.append(f"Unknown platform '{plan.platform}'.\n"
                       f"   Available: {', '.join(config.CHANNEL_PLATFORMS)}.")
            return out                     # channel names cannot be judged without a platform

        requested = plan.requested_channels
        if "all" in requested and len(requested) > 1:
            out.append(f"'--channel all' cannot be combined with named channels.\n"
                       f"   It already means every channel '{plan.platform}' provides: "
                       f"{', '.join(plan.known_channels)}.")
        elif requested and requested != ("all",):
            unknown = [c for c in requested if c not in plan.known_channels]
            if unknown:
                out.append(f"Unknown channel(s) for '{plan.platform}': {', '.join(unknown)}.\n"
                           f"   Available: {', '.join(plan.known_channels)}, or 'all'.")

        if plan.universe and plan.platform_key != "git":
            out.append(
                "'--universe' applies only to the git commit channel.\n"
                "   Issues, pull requests and comments are not commits, so a commit SHA\n"
                "   cannot bound them. The pinned universe still constrains them, but at\n"
                "   LINKAGE: a record whose reference falls outside it never joins the ledger.")
        return out

    # ------------------------------------------------------------------ file resolution

    @staticmethod
    def _find(fname: str) -> Optional[Path]:
        """
        A bare filename is looked up in the directories these files normally live in, so the
        user does not have to remember which one. A path with a directory in it is taken
        literally.
        """
        p = Path(fname)
        if p.parent != Path("."):
            return p if p.exists() else None
        for base in (config.GRID_PATH, config.OUTPUTS_PATH, config.VERSIONS_PATH):
            if (base / p.name).exists():
                return base / p.name
        return None

    def _resolve_files(self, plan: RunPlan):
        errors, universe_path, sample_path = [], None, None

        if plan.universe:
            universe_path = self._find(plan.universe)
            if universe_path is None:
                errors.append(f"--universe file not found: {plan.universe}\n"
                              f"   Looked in {config.GRID_PATH}, {config.OUTPUTS_PATH}.\n"
                              f"   Use --full to mine the whole repository instead.")

        if plan.sample:
            sample_path = self._find(plan.sample)
            if sample_path is None:
                errors.append(f"--sample file not found: {plan.sample}\n"
                              f"   Looked in {config.VERSIONS_PATH}.")

        return universe_path, sample_path, errors
