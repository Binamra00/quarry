import json
from typing import List, Generator


class StackBasedJsonParser:
    """
    A robust parser that extracts ALL valid JSON objects from dirty strings.
    Handles multiple JSON objects in one stream and ignores braces inside strings.
    """

    @staticmethod
    def extract_all(raw_output: str) -> Generator[dict, None, None]:
        """
        Yields all valid JSON objects found in the string.
        Scans strictly, ignoring string literals and non-JSON text.
        """
        if not raw_output:
            return

        cursor = 0
        length = len(raw_output)

        while cursor < length:
            # Find the next potential start
            start_index = raw_output.find('{', cursor)
            if start_index == -1:
                break

            brace_count = 0
            in_string = False
            escape = False

            # Scan from this brace
            # [COPILOT FIX] Variable 'i' tracks current position
            for i in range(start_index, length):
                char = raw_output[i]

                # Handle String Literals (Ignore braces inside quotes)
                if in_string:
                    if escape:
                        escape = False
                    elif char == '\\':
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue  # Skip processing braces while in string

                # Check for string start
                if char == '"':
                    in_string = True
                    continue

                # Handle Braces
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1

                # If counter hits zero, we found a complete balanced block
                if brace_count == 0:
                    potential_json = raw_output[start_index: i + 1]
                    try:
                        # Validate and Yield
                        obj = json.loads(potential_json)
                        yield obj

                        # Advance cursor past this object to find the next one
                        cursor = i + 1
                        break
                    except json.JSONDecodeError:
                        # If invalid (e.g. log text), just advance one char and retry
                        # [COPILOT FIX] Renamed 'candidate_found' logic to simple control flow
                        cursor = start_index + 1
                        break
            else:
                # Loop finished without brace_count == 0 (Unbalanced tail)
                # [COPILOT FIX] If no balanced JSON block was found, stop searching.
                break