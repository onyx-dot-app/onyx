#!/usr/bin/env python

"""Utility to generate mapping from test file IDs to actual Box file IDs."""

import os

from onyx.connectors.box.connector import BoxConnector
from tests.daily.connectors.box.conftest import get_credentials_from_env
from tests.daily.connectors.box.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import file_name_template
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_3_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import load_all_docs


def generate_test_id_to_box_id_mapping() -> dict[int, str]:
    """
    Generate a mapping from test file IDs to actual Box file IDs.

    This is useful for writing tests that need to verify specific files
    are accessible to specific users.

    Returns:
        dict: Mapping from test file ID (int) to Box file URL (str)
    """
    # Set up the connector with real credentials
    # For tests, scope to test parent folder instead of root
    test_parent_folder_id = os.environ.get("BOX_TEST_PARENT_FOLDER_ID")
    if test_parent_folder_id:
        connector = BoxConnector(
            include_all_files=False,
            folder_ids=test_parent_folder_id,
        )
    else:
        connector = BoxConnector(
            include_all_files=True,
            folder_ids=None,
        )

    # Load credentials
    connector.load_credentials(get_credentials_from_env("admin"))

    # Get all documents from the connector
    docs = load_all_docs(connector)

    # Create a mapping from test file ID to actual Box file URL
    test_id_to_box_id = {}

    # Process all documents retrieved from Box
    for doc in docs:
        # Check if this document's name matches our test file naming pattern (file_X.txt)
        if not doc.semantic_identifier.startswith(
            file_name_template.format("").split("_")[0]
        ):
            continue

        try:
            # Extract the test file ID from the filename (file_X.txt -> X)
            file_id_str = doc.semantic_identifier.split("_")[1].split(".")[0]
            test_file_id = int(file_id_str)

            # Store the mapping from test ID to actual Box file URL
            # Box document IDs are URLs
            test_id_to_box_id[test_file_id] = doc.id
        except (ValueError, IndexError):
            # Skip files that don't follow our naming convention
            continue

    # Print the mapping for all defined test file ID ranges
    all_test_ranges = {
        "ADMIN_FILE_IDS": ADMIN_FILE_IDS,
        "FOLDER_1_FILE_IDS": FOLDER_1_FILE_IDS,
        "FOLDER_1_1_FILE_IDS": FOLDER_1_1_FILE_IDS,
        "FOLDER_1_2_FILE_IDS": FOLDER_1_2_FILE_IDS,
        "FOLDER_2_FILE_IDS": FOLDER_2_FILE_IDS,
        "FOLDER_2_1_FILE_IDS": FOLDER_2_1_FILE_IDS,
        "FOLDER_2_2_FILE_IDS": FOLDER_2_2_FILE_IDS,
        "FOLDER_3_FILE_IDS": FOLDER_3_FILE_IDS,
    }

    # Print the mapping for each test range
    for range_name, file_ids in all_test_ranges.items():
        print(f"\n{range_name}:")
        for test_id in file_ids:
            box_id = test_id_to_box_id.get(test_id, "NOT_FOUND")
            print(f"  {test_id} -> {box_id}")

    return test_id_to_box_id


if __name__ == "__main__":
    # Allow running this script directly to generate mappings
    generate_test_id_to_box_id_mapping()
