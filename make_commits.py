#!/usr/bin/env python3
import os
import random
import subprocess
from datetime import datetime, timedelta

# Define the date range
start_date = datetime(2025, 3, 14)  # March 14, 2025
end_date = datetime(2025, 3, 21)    # March 21, 2025
current_date = start_date

# File to modify for each commit
with open("README.md", "w") as f:
    f.write("# Onyx Backfill Project\n\nThis is a demonstration project.\n")

# Make initial commit
subprocess.run(["git", "add", "README.md"])
subprocess.run(["git", "commit", "-m", "Initial commit"])

# Define possible file types and content templates
file_types = [".md", ".txt", ".py", ".js", ".html", ".css", ".json"]
commit_messages = [
    "Update documentation",
    "Fix bug in module",
    "Add new feature",
    "Refactor code",
    "Improve performance",
    "Update dependencies",
    "Clean up code",
    "Add tests",
    "Fix typo",
    "Merge changes"
]

# Loop through each day in the range
while current_date <= end_date:
    # Decide how many commits to make for this day (5-10)
    num_commits = random.randint(5, 10)
    
    for i in range(num_commits):
        # Create or modify a random file
        file_ext = random.choice(file_types)
        file_name = f"file_{random.randint(1, 20)}{file_ext}"
        
        # Add some random content
        with open(file_name, "a") as f:
            f.write(f"Update on {current_date.strftime('%Y-%m-%d')} at commit {i+1}\n")
            
            # Add more content based on file type
            if file_ext == ".py":
                f.write(f"def function_{random.randint(1, 100)}():\n    return 'Hello World!'\n\n")
            elif file_ext == ".js":
                f.write(f"function function_{random.randint(1, 100)}() {{\n    return 'Hello World!';\n}}\n\n")
            elif file_ext == ".html":
                f.write(f"<div class='container-{random.randint(1, 100)}'>Content update</div>\n")
            elif file_ext == ".json":
                f.write(f'{{"update": {i+1}, "timestamp": "{current_date.isoformat()}"}}\n')
        
        # Commit with the specified date
        message = random.choice(commit_messages)
        
        # Add a small random time offset for each commit
        hour = random.randint(9, 17)  # Work hours
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        date_time_str = f"{current_date.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:{second:02d}"
        
        os.environ["GIT_AUTHOR_DATE"] = date_time_str
        os.environ["GIT_COMMITTER_DATE"] = date_time_str
        
        subprocess.run(["git", "add", file_name])
        subprocess.run(["git", "commit", "-m", f"{message} - {file_name}"])
        
        print(f"Created commit for {date_time_str}: {message} - {file_name}")
    
    print(f"Created {num_commits} commits for {current_date.strftime('%Y-%m-%d')}")
    current_date += timedelta(days=1)

print("All commits created successfully!") 