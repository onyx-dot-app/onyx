#!/usr/bin/env python

import json
import os

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from tests.daily.connectors.google_drive.conftest import get_credentials_from_env
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import file_name_template
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import load_all_docs
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_3_FILE_IDS


def generate_test_id_to_drive_id_mapping() -> dict[int, str]:
    """
    Generate a mapping from test file IDs to actual Google Drive file IDs.

    This is useful for writing tests that need to verify specific files
    are accessible to specific users.

    Returns:
        dict: Mapping from test file ID (int) to Google Drive file ID (str)
    """
    # Set up the connector with real credentials
    connector = GoogleDriveConnector(
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=False,
    )

    # Load credentials
    connector.load_credentials(get_credentials_from_env(email=ADMIN_EMAIL, oauth=False))

    # Get all documents from the connector
    docs = load_all_docs(connector)

    # Create a mapping from test file ID to actual Drive file ID
    test_id_to_drive_id = {}

    # Process all documents retrieved from Drive
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

            # Store the mapping from test ID to actual Drive ID
            # Extract Drive ID from document URL
            test_id_to_drive_id[test_file_id] = doc.id
        except (ValueError, IndexError):
            # Skip files that don't follow our naming convention
            continue

    # Print the mapping for all defined test file ID ranges
    all_test_ranges = {
        "ADMIN_FILE_IDS": ADMIN_FILE_IDS,
        "TEST_USER_1_FILE_IDS": TEST_USER_1_FILE_IDS,
        "TEST_USER_2_FILE_IDS": TEST_USER_2_FILE_IDS,
        "TEST_USER_3_FILE_IDS": TEST_USER_3_FILE_IDS,
        "SHARED_DRIVE_1_FILE_IDS": SHARED_DRIVE_1_FILE_IDS,
        "SHARED_DRIVE_2_FILE_IDS": SHARED_DRIVE_2_FILE_IDS,
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
            drive_id = test_id_to_drive_id.get(test_id, "NOT_FOUND")
            print(f"  {test_id} -> {drive_id}")

    return test_id_to_drive_id


@pytest.mark.skipif(
    not os.getenv("RUN_MANUAL_TESTS"),
    reason="This test maps test IDs to actual Google Drive IDs. Set RUN_MANUAL_TESTS=1 to run.",
)
def test_generate_drive_id_mapping() -> None:
    """Test to generate mapping from test IDs to actual Google Drive IDs.

    This test is skipped by default as it requires real Google Drive credentials
    and is primarily used to generate mappings for other tests.

    Run with:

    RUN_MANUAL_TESTS=true pytest -xvs tests/daily/connectors/google_drive/test_map_test_ids.py::test_generate_drive_id_mapping
    """
    mapping = generate_test_id_to_drive_id_mapping()
    assert mapping, "Failed to generate any test ID to drive ID mappings"

    # Write the mapping to a JSON file
    output_dir = os.path.dirname(os.path.abspath(__file__))
    mapping_file = os.path.join(output_dir, "drive_id_mapping.json")

    # Convert int keys to strings for JSON compatibility
    json_mapping = {str(k): v for k, v in mapping.items()}

    # Write the mapping to a JSON file
    with open(mapping_file, "w") as f:
        json.dump(json_mapping, f, indent=2)

    print(f"\nMapping written to: {mapping_file}")
    raise RuntimeError("Mapping written to file, test complete")
