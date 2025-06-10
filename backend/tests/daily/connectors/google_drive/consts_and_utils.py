import time
from collections.abc import Sequence

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector

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
FOLDER_3_FILE_IDS = list(range(62, 65))

DONWLOAD_REVOKED_FILE_ID = 21

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

EXTERNAL_SHARED_FOLDER_URL = (
    "https://drive.google.com/drive/folders/1sWC7Oi0aQGgifLiMnhTjvkhRWVeDa-XS"
)
EXTERNAL_SHARED_DOCS_IN_FOLDER = [
    "https://docs.google.com/document/d/1Sywmv1-H6ENk2GcgieKou3kQHR_0te1mhIUcq8XlcdY"
]
EXTERNAL_SHARED_DOC_SINGLETON = (
    "https://docs.google.com/document/d/11kmisDfdvNcw5LYZbkdPVjTOdj-Uc5ma6Jep68xzeeA"
)

SHARED_DRIVE_3_URL = "https://drive.google.com/drive/folders/0AJYm2K_I_vtNUk9PVA"

RESTRICTED_ACCESS_FOLDER_URL = (
    "https://drive.google.com/drive/folders/1HK4wZ16ucz8QGywlcS87Y629W7i7KdeN"
)

PADDING_DRIVE_URLS = [
    "0AOorXE6AfJRAUk9PVA",
    "0ANn2MSqGi74JUk9PVA",
    "0ANI_NFCPzaRwUk9PVA",
    "0ABu8fYjvA21dUk9PVA",
]

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
        "Title\n"
        "This is a Google Doc with sections - "
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

MISC_SHARED_DRIVE_FNAMES = [
    "asdfasdfsfad",
    "perm_sync_doc_0ABec4pV29sMuUk9PVA_a5ea8ec4-0440-4926-a43d-3aeef1c10bdd",
    "perm_sync_doc_0ACOrCU1EMD1hUk9PVA_651821cb-8140-42fe-a876-1a92012375c9",
    "perm_sync_doc_0ACOrCU1EMD1hUk9PVA_ab63b976-effb-49af-84e7-423d17a17dd7",
    "super secret thing that test user 1 can't see",
    "perm_sync_doc_0ABec4pV29sMuUk9PVA_419f2ef0-9815-4c69-8435-98b163c9c156",
    "Untitled documentfsdfsdfsdf",
    "bingle_bongle.txt",
    "bb4.txt",
    "bb3.txt",
    "bb2.txt",
]

file_name_template = "file_{}.txt"
file_text_template = "This is file {}"

# This is done to prevent different tests from interfering with each other
# So each test type should have its own valid prefix
_VALID_PREFIX = "file_"


def filter_invalid_prefixes(names: set[str]) -> set[str]:
    return {name for name in names if name.startswith(_VALID_PREFIX)}


def print_discrepancies(
    expected: set[str],
    retrieved: set[str],
) -> None:
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
    if file_id in SPECIAL_FILE_ID_TO_CONTENT_MAP:
        return SPECIAL_FILE_ID_TO_CONTENT_MAP[file_id]

    return file_text_template.format(file_id)


def id_to_name(file_id: int) -> str:
    return file_name_template.format(file_id)


def assert_expected_docs_in_retrieved_docs(
    retrieved_docs: list[Document],
    expected_file_ids: Sequence[int],
) -> None:
    """NOTE: as far as i can tell this does NOT assert for an exact match.
    it only checks to see if that the expected file id's are IN the retrieved doc list
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
    valid_retrieved_file_names = set(
        [doc.semantic_identifier for doc in valid_retrieved_docs]
    )
    valid_retrieved_texts = set(
        [
            " - ".join(
                [
                    section.text
                    for section in doc.sections
                    if isinstance(section, TextSection) and section.text is not None
                ]
            )
            for doc in valid_retrieved_docs
        ]
    )

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


def load_all_docs(connector: GoogleDriveConnector) -> list[Document]:
    return load_all_docs_from_checkpoint_connector(
        connector,
        0,
        time.time(),
    )


def load_all_docs_with_failures(
    connector: GoogleDriveConnector,
) -> list[Document | ConnectorFailure]:
    return load_everything_from_checkpoint_connector(
        connector,
        0,
        time.time(),
    )
