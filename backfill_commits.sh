#!/bin/bash

# Define the date range
start_date="2025-03-14"
end_date="2025-03-21"

# Loop through each day in the range
current_date=$start_date
while [ "$current_date" != "$(date -j -v+1d -f "%Y-%m-%d" "$end_date" "+%Y-%m-%d")" ]; do
    echo "Processing date: $current_date"
    
    # Decide how many commits to make for this day (5-10)
    num_commits=$((RANDOM % 6 + 5))
    echo "Will make $num_commits commits for this day"
    
    for ((i=1; i<=num_commits; i++)); do
        # Create a random file name
        file_name="file_$RANDOM.txt"
        
        # Add some random content
        echo "Update on $current_date at commit $i" > "$file_name"
        
        # Create a random time
        hour=$((RANDOM % 9 + 9))  # 9 AM to 5 PM
        minute=$((RANDOM % 60))
        second=$((RANDOM % 60))
        commit_time="$hour:$minute:$second"
        
        # Format for git's date strings
        git_date="$current_date $commit_time"
        
        # Add and commit with the specified date
        git add "$file_name"
        GIT_AUTHOR_DATE="$git_date" GIT_COMMITTER_DATE="$git_date" git commit -m "Update $file_name"
        
        echo "Created commit for $git_date: Update $file_name"
    done
    
    # Move to next day
    current_date=$(date -j -v+1d -f "%Y-%m-%d" "$current_date" "+%Y-%m-%d")
done

echo "All commits created successfully!" 