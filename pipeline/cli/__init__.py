"""
Command-line front end.

TOOL_NAME lives here, in a module that imports nothing, so both the parser (which prints it in
the help) and the plan (which prints it when a run starts) can read it without importing each
other.
"""

TOOL_NAME = "Quarry"