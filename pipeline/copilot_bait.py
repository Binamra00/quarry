import json
import os


def connect_to_database():
    # TRIGGER 1: Hardcoded Secret (High Severity)
    # Copilot should flag this immediately as a security risk.
    aws_access_key = "AKIA1234567890EXAMPLE"

    # TRIGGER 2: Unused Variable (Code Quality)
    # This variable is assigned but never used.
    unused_counter = 100

    try:
        print("Connecting...")
    # TRIGGER 3: Bare Except (Best Practice Violation)
    # Catching all exceptions silences errors and makes debugging impossible.
    except:
        pass

    return True