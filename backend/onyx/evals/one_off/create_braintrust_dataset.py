#!/usr/bin/env python3
"""
Script to create a Braintrust dataset from the DR Master Question & Metric Sheet CSV.

This script:
1. Parses the CSV file
2. Filters records where "Should we use it" is TRUE and "web-only" is in categories
3. Creates a Braintrust dataset with Question as input and research_type metadata
"""

import csv
import os
import sys
from typing import Any
from typing import Dict
from typing import List

try:
    from braintrust import init_dataset
except ImportError:
    print(
        "Error: braintrust package not found. Please install it with: pip install braintrust"
    )
    sys.exit(1)


def parse_csv_file(csv_path: str) -> List[Dict[str, Any]]:
    """Parse the CSV file and extract relevant records."""
    records = []

    with open(csv_path, "r", encoding="utf-8") as file:
        # Skip the first few header rows and read the actual data
        lines = file.readlines()

        # Find the actual data start (skip header rows)
        data_start = 0
        for i, line in enumerate(lines):
            if "Should we use it?" in line:
                data_start = i + 1
                break

        # Parse the CSV data starting from the data_start line
        csv_reader = csv.reader(lines[data_start:])

        for row_num, row in enumerate(csv_reader, start=data_start + 1):
            if len(row) < 13:  # Ensure we have enough columns
                continue

            # Extract relevant fields based on CSV structure
            should_use = row[1].strip().upper() if len(row) > 1 else ""
            question = row[7].strip() if len(row) > 7 else ""
            expected_depth = row[9].strip() if len(row) > 9 else ""
            categories = row[12].strip() if len(row) > 12 else ""

            # Filter records: should_use = TRUE and categories contains "web-only"
            if (
                should_use == "TRUE" and "web-only" in categories.lower() and question
            ):  # Ensure question is not empty

                # Map expected depth to research_type
                research_type = (
                    "DEEP" if expected_depth.upper() == "DEEP" else "THOUGHTFUL"
                )

                records.append(
                    {
                        "question": question,
                        "research_type": research_type,
                        "categories": categories,
                        "expected_depth": expected_depth,
                        "row_number": row_num,
                    }
                )

    return records


def create_braintrust_dataset(records: List[Dict[str, Any]]) -> None:
    """Create a Braintrust dataset with the filtered records."""

    # Check if BRAINTRUST_API_KEY is set
    if not os.getenv("BRAINTRUST_API_KEY"):
        print("WARNING: BRAINTRUST_API_KEY environment variable is not set.")
        print(
            "The script will show what would be inserted but won't actually create the dataset."
        )
        print(
            "To actually create the dataset, set your BRAINTRUST_API_KEY environment variable."
        )
        print()

        # Show what would be inserted
        print(f"Would create Braintrust dataset with {len(records)} records:")
        for i, record in enumerate(records, 1):
            print(f"Record {i}/{len(records)}:")
            print(f"  Question: {record['question'][:100]}...")
            print(f"  Research Type: {record['research_type']}")
            print()
        return

    # Initialize the dataset
    dataset = init_dataset(
        "My Project", "WebEval", api_key=os.getenv("BRAINTRUST_API_KEY")
    )

    print(f"Creating Braintrust dataset with {len(records)} records...")

    # Insert records into the dataset
    for i, record in enumerate(records, 1):
        record_id = dataset.insert(
            {"message": record["question"], "research_type": record["research_type"]}
        )
        print(f"Inserted record {i}/{len(records)}: ID {record_id}")
        print(f"  Question: {record['question'][:100]}...")
        print(f"  Research Type: {record['research_type']}")
        print()

    # Flush to ensure all records are sent
    dataset.flush()
    print(f"Successfully created dataset with {len(records)} records!")


def main():
    """Main function to run the script."""
    csv_path = "/Users/richardguan/onyx/backend/onyx/evals/data/DR Master Question & Metric Sheet - Sheet1.csv"

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)

    print("Parsing CSV file...")
    records = parse_csv_file(csv_path)

    print(f"Found {len(records)} records matching criteria:")
    print("- Should we use it = TRUE")
    print("- Categories contains 'web-only'")
    print("- Question is not empty")
    print()

    if not records:
        print("No records found matching the criteria!")
        sys.exit(1)

    # Show summary of research types
    deep_count = sum(1 for r in records if r["research_type"] == "DEEP")
    thoughtful_count = sum(1 for r in records if r["research_type"] == "THOUGHTFUL")

    print("Research type breakdown:")
    print(f"  DEEP: {deep_count}")
    print(f"  THOUGHTFUL: {thoughtful_count}")
    print()

    # Create the Braintrust dataset
    create_braintrust_dataset(records)


if __name__ == "__main__":
    main()
