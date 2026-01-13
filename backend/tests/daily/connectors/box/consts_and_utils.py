import time
from collections.abc import Sequence

from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector

# File ID ranges for different test scenarios
# These should match actual file IDs in the test Box account
ALL_FILES = list(range(0, 60))
ROOT_FOLDER_FILES = list(range(0, 10))

ADMIN_FILE_IDS = list(range(0, 5))
ADMIN_FOLDER_3_FILE_IDS = list(range(65, 70))  # This folder is shared with test_user_1
TEST_USER_1_FILE_IDS = list(range(5, 10))
TEST_USER_2_FILE_IDS = list(range(10, 15))
TEST_USER_3_FILE_IDS = list(range(15, 20))
FOLDER_1_FILE_IDS = list(range(25, 30))
FOLDER_1_1_FILE_IDS = list(range(30, 35))
FOLDER_1_2_FILE_IDS = list(range(35, 40))  # This folder is public
FOLDER_2_FILE_IDS = list(range(45, 50))
FOLDER_2_1_FILE_IDS = list(range(50, 55))
FOLDER_2_2_FILE_IDS = list(range(55, 60))
SECTIONS_FILE_IDS = [61]
FOLDER_3_FILE_IDS = list(range(62, 65))

DOWNLOAD_REVOKED_FILE_ID = 21

PUBLIC_FOLDER_RANGE = FOLDER_1_2_FILE_IDS
PUBLIC_FILE_IDS = list(range(55, 57))
PUBLIC_RANGE = PUBLIC_FOLDER_RANGE + PUBLIC_FILE_IDS

# Box folder IDs (these should match actual folder IDs in test account)
FOLDER_1_ID = "360287594085"  # Replace with actual folder ID
FOLDER_1_1_ID = "360286151062"  # Replace with actual folder ID
FOLDER_1_2_ID = "360285966218"  # Replace with actual folder ID
FOLDER_2_ID = "360288222616"  # Replace with actual folder ID
FOLDER_2_1_ID = "360287577597"  # Replace with actual folder ID
FOLDER_2_2_ID = "360286012378"  # Replace with actual folder ID
FOLDER_3_ID = "360285724765"  # Replace with actual folder ID
ADMIN_FOLDER_3_ID = "360286714903"  # Admin's Folder 3 (shared with test_user_1)
SECTIONS_FOLDER_ID = "360288138769"  # Replace with actual folder ID

# Box folder URLs
FOLDER_1_URL = f"https://app.box.com/folder/{FOLDER_1_ID}"
FOLDER_1_1_URL = f"https://app.box.com/folder/{FOLDER_1_1_ID}"
FOLDER_1_2_URL = f"https://app.box.com/folder/{FOLDER_1_2_ID}"
FOLDER_2_URL = f"https://app.box.com/folder/{FOLDER_2_ID}"
FOLDER_2_1_URL = f"https://app.box.com/folder/{FOLDER_2_1_ID}"
FOLDER_2_2_URL = f"https://app.box.com/folder/{FOLDER_2_2_ID}"
FOLDER_3_URL = f"https://app.box.com/folder/{FOLDER_3_ID}"
ADMIN_FOLDER_3_URL = f"https://app.box.com/folder/{ADMIN_FOLDER_3_ID}"
SECTIONS_FOLDER_URL = f"https://app.box.com/folder/{SECTIONS_FOLDER_ID}"

RESTRICTED_ACCESS_FOLDER_ID = "123456797"  # Replace with actual folder ID
RESTRICTED_ACCESS_FOLDER_URL = (
    f"https://app.box.com/folder/{RESTRICTED_ACCESS_FOLDER_ID}"
)

# User IDs (these should match actual Box user IDs)
ADMIN_USER_ID = "13089353657"  # Replace with actual user ID
TEST_USER_1_ID = "48129700105"  # Replace with actual user ID
TEST_USER_2_ID = "48129680809"  # Replace with actual user ID
TEST_USER_3_ID = "48129580359"  # Replace with actual user ID

# Dictionary for access permissions
# All users have access to their own files as well as public files
ACCESS_MAPPING: dict[str, list[int]] = {
    # Admin has access to everything in the test parent folder
    ADMIN_USER_ID: (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + FOLDER_3_FILE_IDS
        + SECTIONS_FILE_IDS
        # Admin can also see all test user files in the test parent folder
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + TEST_USER_3_FILE_IDS
    ),
    TEST_USER_1_ID: (
        TEST_USER_1_FILE_IDS
        # This user has access to folder 1
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        # This user has been given shared access to Admin's Folder 3
        + ADMIN_FOLDER_3_FILE_IDS
        # This user has been given shared access to files 0 and 1 in Admin's root
        + list(range(0, 2))
        # When scoped to test parent folder, user can see all subfolders
        # So they can also see FOLDER_3 and other folders
        + FOLDER_3_FILE_IDS
        + SECTIONS_FILE_IDS
        # They can also see files 2-4, 10-19 from other users' folders
        # because they have access to the test parent folder
        + list(range(2, 5))
        + list(range(10, 20))
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
    ),
    TEST_USER_2_ID: (
        TEST_USER_2_FILE_IDS
        # Group 1 includes this user, giving access to folder 1
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        # This folder is public
        + FOLDER_1_2_FILE_IDS
        # Folder 2-1 is shared with this user
        + FOLDER_2_1_FILE_IDS
        # This user has been given shared access to files 45 and 46 in folder 2
        + list(range(45, 47))
    ),
    # When include_all_files=True is scoped to test parent folder,
    # all users can see all subfolders (Box behavior when user has access to parent folder)
    TEST_USER_3_ID: (
        TEST_USER_3_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + FOLDER_3_FILE_IDS
        + SECTIONS_FILE_IDS
        + ADMIN_FILE_IDS
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
    ),
}

SPECIAL_FILE_ID_TO_CONTENT_MAP: dict[int, str] = {
    61: (
        "Title\n"
        "This is a Box document with sections - "
        "Section 1\n"
        "Section 1 content - "
        "Sub-Section 1-1\n"
        "Sub-Section 1-1 content - "
        "Sub-Section 1-2\n"
        "Sub-Section 1-2 content - "
        "Section 2\n"
        "Section 2 content"
    ),
}

file_name_template = "file_{}.txt"
file_text_template = "This is file {}"

# This is done to prevent different tests from interfering with each other
# So each test type should have its own valid prefix
_VALID_PREFIX = "file_"


def filter_invalid_prefixes(names: set[str]) -> set[str]:
    """Filter out file names that don't match the valid prefix."""
    return {name for name in names if name.startswith(_VALID_PREFIX)}


def print_discrepancies(
    expected: set[str],
    retrieved: set[str],
) -> None:
    """Print discrepancies between expected and retrieved file names."""
    if expected != retrieved:
        expected_list = sorted(expected)
        retrieved_list = sorted(retrieved)
        print(expected_list)
        print(retrieved_list)
        print("Extra:")
        print(sorted(retrieved - expected))
        print("Missing:")
        print(sorted(expected - retrieved))


def _get_expected_file_content(file_id: int) -> str:
    """Get expected file content for a given file ID."""
    if file_id in SPECIAL_FILE_ID_TO_CONTENT_MAP:
        return SPECIAL_FILE_ID_TO_CONTENT_MAP[file_id]

    return file_text_template.format(file_id)


def id_to_name(file_id: int) -> str:
    """Convert file ID to expected filename."""
    return file_name_template.format(file_id)


def assert_expected_docs_in_retrieved_docs(
    retrieved_docs: list[Document],
    expected_file_ids: Sequence[int],
) -> None:
    """
    Assert that expected file IDs are present in retrieved documents.

    NOTE: This asserts for an exact match after filtering to valid prefixes.
    It filters retrieved docs to those with the valid prefix, then asserts
    that the expected file names and texts exactly match the filtered retrieved docs.
    """
    expected_file_names = {id_to_name(file_id) for file_id in expected_file_ids}
    expected_file_texts = {
        _get_expected_file_content(file_id) for file_id in expected_file_ids
    }

    retrieved_docs.sort(key=lambda x: x.semantic_identifier)

    for doc in retrieved_docs:
        print(f"retrieved doc: doc.semantic_identifier={doc.semantic_identifier}")

    # Filter out invalid prefixes to prevent different tests from interfering with each other
    valid_retrieved_docs = [
        doc
        for doc in retrieved_docs
        if doc.semantic_identifier.startswith(_VALID_PREFIX)
    ]

    # Check for duplicate semantic identifiers before building mapping
    semantic_identifiers = [doc.semantic_identifier for doc in valid_retrieved_docs]
    seen_identifiers = set()
    duplicates = []
    for identifier in semantic_identifiers:
        if identifier in seen_identifiers:
            duplicates.append(identifier)
        seen_identifiers.add(identifier)
    if duplicates:
        raise AssertionError(
            f"Found duplicate semantic_identifiers in retrieved docs: {duplicates}. "
            f"This indicates a bug in the connector that returns the same document multiple times."
        )

    # Create mapping from file name to file text to detect mismatches
    retrieved_name_to_text: dict[str, str] = {}
    for doc in valid_retrieved_docs:
        text = " - ".join(
            [
                section.text
                for section in doc.sections
                if isinstance(section, TextSection) and section.text is not None
            ]
        )
        retrieved_name_to_text[doc.semantic_identifier] = text

    valid_retrieved_file_names = set(retrieved_name_to_text.keys())
    valid_retrieved_texts = set(retrieved_name_to_text.values())

    # Check file names
    print_discrepancies(
        expected=expected_file_names,
        retrieved=valid_retrieved_file_names,
    )
    assert expected_file_names == valid_retrieved_file_names

    # Check file texts
    print_discrepancies(
        expected=expected_file_texts,
        retrieved=valid_retrieved_texts,
    )
    assert expected_file_texts == valid_retrieved_texts

    # Verify that each file name has the correct corresponding text
    # (This prevents swapped or mismatched file content per name from passing)
    for file_id in expected_file_ids:
        expected_name = id_to_name(file_id)
        expected_text = _get_expected_file_content(file_id)
        if expected_name in retrieved_name_to_text:
            retrieved_text = retrieved_name_to_text[expected_name]
            assert retrieved_text == expected_text, (
                f"File {expected_name} has incorrect content. "
                f"Expected: {expected_text}, Got: {retrieved_text}"
            )


def load_all_docs(connector: BoxConnector) -> list[Document]:
    """Load all documents from a Box connector."""
    return load_all_docs_from_checkpoint_connector(
        connector,
        0,
        time.time(),
    )


def load_all_docs_with_failures(
    connector: BoxConnector,
) -> list[Document | ConnectorFailure]:
    """Load all documents from a Box connector, including failures."""
    return load_everything_from_checkpoint_connector(
        connector,
        0,
        time.time(),
    )
