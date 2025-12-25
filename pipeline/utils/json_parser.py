import json
from typing import Optional


class StackBasedJsonParser:
    """
    A robust parser that extracts valid JSON objects from dirty strings
    (e.g., mixed with logs) using a stack-based bracket counting approach.
    """

    @staticmethod
    def extract_json(raw_output: str) -> Optional[dict]:
        """
        Locates the first *VALID* JSON object in a string by counting braces.
        If a candidate substring fails JSON parsing (e.g. log text),
        it continues searching the rest of the string.
        """
        if not raw_output:
            return None

        cursor = 0
        while cursor < len(raw_output):
            # Find the next opening brace
            start_index = raw_output.find('{', cursor)
            if start_index == -1:
                break  # No more JSON candidates

            brace_count = 0
            in_json = False
            candidate_found = False
            end_index = -1

            # Scan from this brace to find its matching closer
            for i, char in enumerate(raw_output[start_index:], start=start_index):
                if char == '{':
                    brace_count += 1
                    in_json = True
                elif char == '}':
                    brace_count -= 1

                # If counter hits zero, we found a complete balanced block
                if in_json and brace_count == 0:
                    potential_json = raw_output[start_index: i + 1]
                    try:
                        # [CRITICAL FIX] Verify it's valid JSON
                        return json.loads(potential_json)
                    except json.JSONDecodeError:
                        # If invalid (e.g. "{Log Message}"), advance cursor and keep searching
                        cursor = start_index + 1
                        candidate_found = True
                        break  # Break inner loop, continue outer while loop

            # If we exited the inner loop without finding a candidate (unbalanced), abort
            if not candidate_found:
                break

        return None