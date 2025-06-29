#!/usr/bin/env python
"""
Script to list all available folders in Freshdesk Knowledge Base.
This helps identify folder IDs to use in the connector configuration.
"""

import argparse
import json
import os
import sys
from typing import Any
from typing import Dict
from typing import List

# Add the onyx module to the path
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../.."))

from onyx.connectors.freshdesk_kb.connector import FreshdeskKnowledgeBaseConnector


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="List all available folders in a Freshdesk Knowledge Base"
    )
    parser.add_argument(
        "--domain",
        type=str,
        required=True,
        help="Freshdesk domain (e.g., company.freshdesk.com)",
    )
    parser.add_argument("--api-key", type=str, required=True, help="Freshdesk API key")
    parser.add_argument(
        "--output",
        type=str,
        default="folders.json",
        help="Output JSON file (default: folders.json)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the output")

    return parser.parse_args()


def list_folders(domain: str, api_key: str) -> List[Dict[str, Any]]:
    """
    List all available folders in the Freshdesk Knowledge Base.

    Args:
        domain: Freshdesk domain
        api_key: Freshdesk API key

    Returns:
        List of folders with their details
    """
    # Initialize connector with just the credentials
    connector = FreshdeskKnowledgeBaseConnector(
        freshdesk_domain=domain,
        freshdesk_api_key=api_key,
    )

    # Use the list_available_folders method to get all folders
    return connector.list_available_folders()


def format_folders(folders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format folder data for display, organizing by category."""
    # Sort folders by category name and then by folder name
    folders = sorted(
        folders, key=lambda f: (f.get("category_name", ""), f.get("name", ""))
    )
    # Add formatted display name with category
    for folder in folders:
        folder["display_name"] = (
            f"{folder.get('name')} [Category: {folder.get('category_name', 'Unknown')}]"
        )

    return folders


def main() -> None:
    """Main function."""
    args = parse_args()
    print(f"Fetching Freshdesk KB folders from domain: {args.domain}")
    try:
        folders = list_folders(args.domain, args.api_key)
        if not folders:
            print("No folders found. Check your credentials and try again.")
            return
        # Format folders for better display
        formatted_folders = format_folders(folders)
        # Print summary to console
        print(f"\nFound {len(formatted_folders)} folders:")
        for i, folder in enumerate(formatted_folders, 1):
            print(f"{i}. ID: {folder.get('id')} - {folder.get('display_name')}")
        # Save full details to file
        output_indent = 2 if args.pretty else None
        with open(args.output, "w") as f:
            json.dump(formatted_folders, f, indent=output_indent)
        print(f"\nFull folder details saved to {args.output}")
        print(
            "\nTo use multiple folders in the Freshdesk KB connector, enter the folder IDs as a comma-separated list."
        )
        print("Example: 12345,67890,54321")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
