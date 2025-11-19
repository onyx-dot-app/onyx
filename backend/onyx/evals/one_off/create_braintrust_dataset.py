#!/usr/bin/env python3
"""
Script to create a Braintrust dataset from the DR Master Question & Metric Sheet CSV.

This script:
1. Parses the CSV file
2. Filters records where "Should we use it" is TRUE and "web-only" is in categories
3. Creates a Braintrust dataset with Question as input and research_type metadata

Usage:
    python create_braintrust_dataset.py --dataset-name "MyDataset"
    python create_braintrust_dataset.py --dataset-name "MyDataset" --csv-path "/path/to/csv"
"""

import argparse
import csv
import os
import sys
from typing import Any
from typing import Dict
from typing import List

from onyx.configs.app_configs import BRAINTRUST_API_KEY

try:
    from braintrust import init_dataset
except ImportError:
    print(
        "Error: braintrust package not found. Please install it with: pip install braintrust"
    )
    sys.exit(1)


def column_letter_to_index(column_letter: str) -> int:
    """Convert Google Sheets column letter (A, B, C, etc.) to 0-based index."""
    result = 0
    for char in column_letter.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


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

        # Define Google Sheets column references for easy modification
        SHOULD_USE_COL = "C"  # "Should we use it?"
        QUESTION_COL = "H"  # "Question"
        EXPECTED_DEPTH_COL = "J"  # "Expected Depth"
        CATEGORIES_COL = "M"  # "Categories"
        OPENAI_DEEP_COL = "AA"  # "OpenAI Deep Answer"
        OPENAI_THINKING_COL = "O"  # "OpenAI Thinking Answer"

        for row_num, row in enumerate(csv_reader, start=data_start + 1):
            if len(row) < 15:  # Ensure we have enough columns
                continue

            # Extract relevant fields using Google Sheets column references
            should_use = (
                row[column_letter_to_index(SHOULD_USE_COL)].strip().upper()
                if len(row) > column_letter_to_index(SHOULD_USE_COL)
                else ""
            )
            question = (
                row[column_letter_to_index(QUESTION_COL)].strip()
                if len(row) > column_letter_to_index(QUESTION_COL)
                else ""
            )
            expected_depth = (
                row[column_letter_to_index(EXPECTED_DEPTH_COL)].strip()
                if len(row) > column_letter_to_index(EXPECTED_DEPTH_COL)
                else ""
            )
            categories = (
                row[column_letter_to_index(CATEGORIES_COL)].strip()
                if len(row) > column_letter_to_index(CATEGORIES_COL)
                else ""
            )
            openai_deep_answer = (
                row[column_letter_to_index(OPENAI_DEEP_COL)].strip()
                if len(row) > column_letter_to_index(OPENAI_DEEP_COL)
                else ""
            )
            openai_thinking_answer = (
                row[column_letter_to_index(OPENAI_THINKING_COL)].strip()
                if len(row) > column_letter_to_index(OPENAI_THINKING_COL)
                else ""
            )

            # Filter records: should_use = TRUE and categories contains "web-only"
            if (
                should_use == "TRUE" and "web-only" in categories and question
            ):  # Ensure question is not empty
                if expected_depth == "Deep":
                    records.extend(
                        [
                            {
                                "question": question
                                + ". All info is contained in the quesiton. DO NOT ask any clarifying questions.",
                                "research_type": "DEEP",
                                "categories": categories,
                                "expected_depth": expected_depth,
                                "expected_answer": openai_deep_answer,
                                "row_number": row_num,
                            }
                        ]
                    )
                else:
                    records.extend(
                        [
                            {
                                "question": question,
                                "research_type": "THOUGHTFUL",
                                "categories": categories,
                                "expected_depth": expected_depth,
                                "expected_answer": openai_thinking_answer,
                                "row_number": row_num,
                            }
                        ]
                    )

    return records


def create_braintrust_dataset(records: List[Dict[str, Any]], dataset_name: str) -> None:
    """Create a Braintrust dataset with the filtered records."""

    # Check if BRAINTRUST_API_KEY is set
    if BRAINTRUST_API_KEY == "":
        print("WARNING: BRAINTRUST_API_KEY environment variable is not set.")
        print(
            "The script will show what would be inserted but won't actually create the dataset."
        )
        print(
            "To actually create the dataset, set your BRAINTRUST_API_KEY environment variable."
        )
        print()

        # Show what would be inserted
        print(
            f"Would create Braintrust dataset '{dataset_name}' with {len(records)} records:"
        )
        for i, record in enumerate(records, 1):
            print(f"Record {i}/{len(records)}:")
            print(f"  Question: {record['question'][:100]}...")
            print(f"  Research Type: {record['research_type']}")
            print(f"  Expected Answer: {record['expected_answer'][:100]}...")
            print()
        return

    # Initialize the dataset
    dataset = init_dataset("Onyx", dataset_name, api_key=BRAINTRUST_API_KEY)

    print(f"Creating Braintrust dataset with {len(records)} records...")

    # Insert records into the dataset
    for i, record in enumerate(records, 1):
        record_id = dataset.insert(
            {"message": record["question"], "research_type": record["research_type"]},
            expected=record["expected_answer"],
        )
        print(f"Inserted record {i}/{len(records)}: ID {record_id}")
        print(f"  Question: {record['question'][:100]}...")
        print(f"  Research Type: {record['research_type']}")
        print(f"  Expected Answer: {record['expected_answer'][:100]}...")
        print()

    # Flush to ensure all records are sent
    dataset.flush()
    print(f"Successfully created dataset with {len(records)} records!")


def main() -> None:
    """Main function to run the script."""
    parser = argparse.ArgumentParser(
        description="Create a Braintrust dataset from the DR Master Question & Metric Sheet CSV"
    )
    parser.add_argument(
        "--dataset-name", required=True, help="Name of the Braintrust dataset to create"
    )
    parser.add_argument(
        "--csv-path",
        default="/Users/richardguan/onyx/backend/onyx/evals/data/DR Master Question & Metric Sheet - Sheet1.csv",
        help="Path to the CSV file (default: %(default)s)",
    )

    args = parser.parse_args()

    csv_path = args.csv_path
    dataset_name = args.dataset_name

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
    create_braintrust_dataset(records, dataset_name)


if __name__ == "__main__":
    main()
