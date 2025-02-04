from collections.abc import Sequence

from onyx.connectors.models import Document

ALL_FILES = list(range(0, 60))
SHARED_DRIVE_FILES = list(range(20, 25))


ADMIN_FILE_IDS = list(range(0, 5))
ADMIN_FOLDER_3_FILE_IDS = list(range(65, 70))  # This folder is shared with test_user_1
TEST_USER_1_FILE_IDS = list(range(5, 10))
TEST_USER_2_FILE_IDS = list(range(10, 15))
TEST_USER_3_FILE_IDS = list(range(15, 20))
SHARED_DRIVE_1_FILE_IDS = list(range(20, 25))
FOLDER_1_FILE_IDS = list(range(25, 30))
FOLDER_1_1_FILE_IDS = list(range(30, 35))
FOLDER_1_2_FILE_IDS = list(range(35, 40))  # This folder is public
SHARED_DRIVE_2_FILE_IDS = list(range(40, 45))
FOLDER_2_FILE_IDS = list(range(45, 50))
FOLDER_2_1_FILE_IDS = list(range(50, 55))
FOLDER_2_2_FILE_IDS = list(range(55, 60))
SECTIONS_FILE_IDS = [61]

PUBLIC_FOLDER_RANGE = FOLDER_1_2_FILE_IDS
PUBLIC_FILE_IDS = list(range(55, 57))
PUBLIC_RANGE = PUBLIC_FOLDER_RANGE + PUBLIC_FILE_IDS

SHARED_DRIVE_1_URL = "https://drive.google.com/drive/folders/0AC_OJ4BkMd4kUk9PVA"
# Group 1 is given access to this folder
FOLDER_1_URL = (
    "https://drive.google.com/drive/folders/1d3I7U3vUZMDziF1OQqYRkB8Jp2s_GWUn"
)
FOLDER_1_1_URL = (
    "https://drive.google.com/drive/folders/1aR33-zwzl_mnRAwH55GgtWTE-4A4yWWI"
)
FOLDER_1_2_URL = (
    "https://drive.google.com/drive/folders/1IO0X55VhvLXf4mdxzHxuKf4wxrDBB6jq"
)
SHARED_DRIVE_2_URL = "https://drive.google.com/drive/folders/0ABKspIh7P4f4Uk9PVA"
FOLDER_2_URL = (
    "https://drive.google.com/drive/folders/1lNpCJ1teu8Se0louwL0oOHK9nEalskof"
)
FOLDER_2_1_URL = (
    "https://drive.google.com/drive/folders/1XeDOMWwxTDiVr9Ig2gKum3Zq_Wivv6zY"
)
FOLDER_2_2_URL = (
    "https://drive.google.com/drive/folders/1RKlsexA8h7NHvBAWRbU27MJotic7KXe3"
)
FOLDER_3_URL = (
    "https://drive.google.com/drive/folders/1LHibIEXfpUmqZ-XjBea44SocA91Nkveu"
)
SECTIONS_FOLDER_URL = (
    "https://drive.google.com/drive/u/5/folders/1loe6XJ-pJxu9YYPv7cF3Hmz296VNzA33"
)

ADMIN_EMAIL = "admin@onyx-test.com"
TEST_USER_1_EMAIL = "test_user_1@onyx-test.com"
TEST_USER_2_EMAIL = "test_user_2@onyx-test.com"
TEST_USER_3_EMAIL = "test_user_3@onyx-test.com"

# Dictionary for access permissions
# All users have access to their own My Drive as well as public files
ACCESS_MAPPING: dict[str, list[int]] = {
    # Admin has access to everything in shared
    ADMIN_EMAIL: (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + SHARED_DRIVE_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + SECTIONS_FILE_IDS
    ),
    TEST_USER_1_EMAIL: (
        TEST_USER_1_FILE_IDS
        # This user has access to drive 1
        + SHARED_DRIVE_1_FILE_IDS
        # This user has redundant access to folder 1 because of group access
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        # This user has been given shared access to folder 3 in Admin's My Drive
        + ADMIN_FOLDER_3_FILE_IDS
        # This user has been given shared access to files 0 and 1 in Admin's My Drive
        + list(range(0, 2))
    ),
    TEST_USER_2_EMAIL: (
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
    # This user can only see his own files and public files
    TEST_USER_3_EMAIL: TEST_USER_3_FILE_IDS,
}

SPECIAL_FILE_ID_TO_CONTENT_MAP: dict[int, str] = {
    61: (
        "Title\n\n"
        "This is a Google Doc with sections - "
        "Section 1\n\n"
        "Section 1 content - "
        "Sub-Section 1-1\n\n"
        "Sub-Section 1-1 content - "
        "Sub-Section 1-2\n\n"
        "Sub-Section 1-2 content - "
        "Section 2\n\n"
        "Section 2 content"
    ),
}


file_name_template = "file_{}.txt"
file_text_template = "This is file {}"

# This is done to prevent different tests from interfering with each other
# So each test type should have its own valid prefix
_VALID_PREFIX = "file_"


def filter_invalid_prefixes(names: set[str]) -> set[str]:
    return {name for name in names if name.startswith(_VALID_PREFIX)}


def print_discrepencies(
    expected: set[str],
    retrieved: set[str],
) -> None:
    if expected != retrieved:
        print(expected)
        print(retrieved)
        print("Extra:")
        print(retrieved - expected)
        print("Missing:")
        print(expected - retrieved)


def _get_expected_file_content(file_id: int) -> str:
    if file_id in SPECIAL_FILE_ID_TO_CONTENT_MAP:
        return SPECIAL_FILE_ID_TO_CONTENT_MAP[file_id]

    return file_text_template.format(file_id)


def assert_retrieved_docs_match_expected(
    retrieved_docs: list[Document],
    expected_file_ids: Sequence[int],
) -> None:
    expected_file_names = {
        file_name_template.format(file_id) for file_id in expected_file_ids
    }
    expected_file_texts = {
        _get_expected_file_content(file_id) for file_id in expected_file_ids
    }

    for doc in retrieved_docs:
        print(f"doc.semantic_identifier: {doc.semantic_identifier}")

    # Filter out invalid prefixes to prevent different tests from interfering with each other
    valid_retrieved_docs = [
        doc
        for doc in retrieved_docs
        if doc.semantic_identifier.startswith(_VALID_PREFIX)
    ]
    valid_retrieved_file_names = set(
        [doc.semantic_identifier for doc in valid_retrieved_docs]
    )
    valid_retrieved_texts = set(
        [
            " - ".join([section.text for section in doc.sections])
            for doc in valid_retrieved_docs
        ]
    )

    # Check file names
    print_discrepencies(
        expected=expected_file_names,
        retrieved=valid_retrieved_file_names,
    )
    assert expected_file_names == valid_retrieved_file_names

    # Check file texts
    print_discrepencies(
        expected=expected_file_texts,
        retrieved=valid_retrieved_texts,
    )
    assert expected_file_texts == valid_retrieved_texts
