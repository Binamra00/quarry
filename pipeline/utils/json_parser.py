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
        Locates the first valid JSON object in a string by counting braces.
        Ignores text before the first '{' and handles nested structures correctly.
        """
        if not raw_output:
            return None

        # Find start of JSON
        start_index = raw_output.find('{')
        if start_index == -1:
            return None

        brace_count = 0
        in_json = False

        # Scan from the first brace
        for i, char in enumerate(raw_output[start_index:], start=start_index):
            if char == '{':
                brace_count += 1
                in_json = True
            elif char == '}':
                brace_count -= 1

            # If counter hits zero, we found the closing brace of the root object
            if in_json and brace_count == 0:
                potential_json = raw_output[start_index: i + 1]
                try:
                    return json.loads(potential_json)
                except json.JSONDecodeError:
                    # If parsing fails, it wasn't valid JSON (e.g. "{INFO}")
                    return None
        return None