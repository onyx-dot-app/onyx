#!/usr/bin/env python
"""
Simple script that keeps trying to run 'alembic upgrade head' until it succeeds.
"""
import subprocess
import sys
import time

# Path to alembic.ini (change this if needed)
ALEMBIC_CONFIG = "alembic.ini"

# Time to wait between attempts (in seconds)
WAIT_TIME = 0

print("Starting continuous alembic upgrade attempts")
print(f"Using config: {ALEMBIC_CONFIG}")
print(f"Will retry every {WAIT_TIME} seconds until successful")

attempt = 1

while True:
    print(f"\nAttempt #{attempt} to run alembic upgrade head")

    try:
        # Run the alembic upgrade head command
        result = subprocess.run(
            ["alembic", "-c", ALEMBIC_CONFIG, "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )

        # If we get here, the command was successful
        print("SUCCESS! Alembic upgrade completed successfully.")
        print(f"Output: {result.stdout}")
        sys.exit(0)

    except subprocess.CalledProcessError as e:
        # Command failed, print error and try again
        print(f"FAILED with return code {e.returncode}")
        print(f"Error output: {e.stderr}")

    print(f"Waiting {WAIT_TIME} seconds before next attempt...")
    time.sleep(WAIT_TIME)
    attempt += 1
