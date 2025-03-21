#!/usr/bin/env python3
import os
import random
import subprocess
from datetime import datetime, timedelta

print("Script starting...")

# Define the date range
start_date = datetime(2025, 3, 14)  # March 14, 2025
end_date = datetime(2025, 3, 21)    # March 21, 2025
current_date = start_date

print(f"Date range: {start_date} to {end_date}")

# Define possible file types and content templates
file_types = [".md", ".txt", ".py", ".js"]
commit_messages = [
    "Update documentation",
    "Fix bug in module",
    "Add new feature",
    "Refactor code"
]

print("Starting loop through dates...")

# Loop through each day in the range
day_count = 0
while current_date <= end_date:
    day_count += 1
    print(f"\nProcessing day {day_count}: {current_date.strftime('%Y-%m-%d')}")
    
    # Decide how many commits to make for this day (5-10)
    num_commits = random.randint(5, 8)
    print(f"Will make {num_commits} commits for this day")
    
    for i in range(num_commits):
        print(f"  Creating commit {i+1}/{num_commits}...")
        
        # Create or modify a random file
        file_ext = random.choice(file_types)
        file_name = f"file_{random.randint(1, 10)}{file_ext}"
        print(f"  Working with file: {file_name}")
        
        # Add some random content
        try:
            with open(file_name, "a") as f:
                f.write(f"Update on {current_date.strftime('%Y-%m-%d')} at commit {i+1}\n")
            print(f"  Added content to {file_name}")
        except Exception as e:
            print(f"  Error writing to file: {e}")
            continue
        
        # Commit with the specified date
        message = random.choice(commit_messages)
        
        # Add a small random time offset for each commit
        hour = random.randint(9, 17)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        date_time_str = f"{current_date.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:{second:02d}"
        
        print(f"  Setting commit date to: {date_time_str}")
        
        try:
            cmd_env = os.environ.copy()
            cmd_env["GIT_AUTHOR_DATE"] = date_time_str
            cmd_env["GIT_COMMITTER_DATE"] = date_time_str
            
            print(f"  Running git add {file_name}")
            result = subprocess.run(["git", "add", file_name], capture_output=True, text=True)
            print(f"  git add output: {result.stdout} {result.stderr}")
            
            print(f"  Running git commit with message: {message} - {file_name}")
            result = subprocess.run(
                ["git", "commit", "-m", f"{message} - {file_name}"], 
                env=cmd_env,
                capture_output=True,
                text=True
            )
            print(f"  git commit output: {result.stdout} {result.stderr}")
            
            print(f"  Created commit for {date_time_str}: {message} - {file_name}")
        except Exception as e:
            print(f"  Error during git operations: {e}")
    
    print(f"Completed {num_commits} commits for {current_date.strftime('%Y-%m-%d')}")
    current_date += timedelta(days=1)

print("\nAll commits created successfully!") 