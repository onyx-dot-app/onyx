#!/bin/bash

# USAGE: nohup ./docker_memory_tracking.sh &

# Set default output file or use the provided argument
OUTPUT_FILE="./docker_stats.log"
if [ $# -ge 1 ]; then
    OUTPUT_FILE="$1"
fi

INTERVAL_SECONDS=600  # 10 minutes

# Create the output file if it doesn't exist, or append to it if it does
touch "$OUTPUT_FILE"

echo "Docker stats will be collected every 10 minutes and saved to $OUTPUT_FILE"
echo "Press Ctrl+C to stop the script"

# Function to handle script termination
cleanup() {
    echo -e "\nStopping docker stats collection"
    exit 0
}

# Set up trap for clean exit
trap cleanup SIGINT SIGTERM

# Main loop
while true; do
    # Add timestamp
    echo -e "\n--- Docker Stats: $(date) ---" >> "$OUTPUT_FILE"
    
    # Run docker stats for a single snapshot (--no-stream ensures it runs once)
    docker stats --no-stream --all >> "$OUTPUT_FILE"
    
    # Wait for the next interval
    echo "Stats collected at $(date). Next collection in 10 minutes."
    sleep $INTERVAL_SECONDS
done
