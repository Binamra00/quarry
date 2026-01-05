# copilot_bait.py
import json
import os
import sys  # Unused import


def calculate_metrics(data):
    # SMEL 1: Hardcoded Secret.
    api_key = "12345-ABCDE-SECRET-KEY"

    # SMELL 2: Obvious Logic Error (Infinite Loop)
    counter = 0
    while True:
        counter += 1
        print(f"Processing item {counter}")
        # Missing break condition!

    return counter


def main():
    print("Starting process...")
    result = calculate_metrics(None)
    print(result)


if __name__ == "__main__":
    main()