import time
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from urllib.parse import urlparse

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from tests.daily.connectors.utils import ConnectorOutput
from tests.daily.connectors.utils import load_all_from_connector

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


def extract_folder_id_from_url(url: str) -> str:
    """Extract the folder ID from a Google Drive URL."""
    parsed = urlparse(url)
    # URL format: /drive/folders/{id} or /drive/u/{num}/folders/{id}
    parts = parsed.path.split("/")
    # Find 'folders' and take the next segment
    for i, part in enumerate(parts):
        if part == "folders" and i + 1 < len(parts):
            return parts[i + 1]
    raise ValueError(f"Could not extract folder ID from URL: {url}")


# Folder IDs extracted from URLs
SHARED_DRIVE_1_ID = extract_folder_id_from_url(SHARED_DRIVE_1_URL)
SHARED_DRIVE_2_ID = extract_folder_id_from_url(SHARED_DRIVE_2_URL)
FOLDER_1_ID = extract_folder_id_from_url(FOLDER_1_URL)
FOLDER_1_1_ID = extract_folder_id_from_url(FOLDER_1_1_URL)
FOLDER_1_2_ID = extract_folder_id_from_url(FOLDER_1_2_URL)
FOLDER_2_ID = extract_folder_id_from_url(FOLDER_2_URL)
FOLDER_2_1_ID = extract_folder_id_from_url(FOLDER_2_1_URL)
FOLDER_2_2_ID = extract_folder_id_from_url(FOLDER_2_2_URL)
FOLDER_3_ID = extract_folder_id_from_url(FOLDER_3_URL)
SECTIONS_FOLDER_ID = extract_folder_id_from_url(SECTIONS_FOLDER_URL)
RESTRICTED_ACCESS_FOLDER_ID = "1HK4wZ16ucz8QGywlcS87Y629W7i7KdeN"


# ============================================================================
# FOLDER HIERARCHY DEFINITION
# ============================================================================
# This defines the expected folder hierarchy for our test Google Drive setup.
#
# Folder Hierarchy:
# shared_drive_1 (0AC_OJ4BkMd4kUk9PVA)
#   ├── restricted_access_folder (1HK4wZ16ucz8QGywlcS87Y629W7i7KdeN)
#   └── folder_1 (1d3I7U3vUZMDziF1OQqYRkB8Jp2s_GWUn)
#       ├── folder_1_1 (1aR33-zwzl_mnRAwH55GgtWTE-4A4yWWI)
#       └── folder_1_2 (1IO0X55VhvLXf4mdxzHxuKf4wxrDBB6jq)
#
# shared_drive_2 (0ABKspIh7P4f4Uk9PVA)
#   ├── sections_folder (1loe6XJ-pJxu9YYPv7cF3Hmz296VNzA33)
#   └── folder_2 (1lNpCJ1teu8Se0louwL0oOHK9nEalskof)
#       ├── folder_2_1 (1XeDOMWwxTDiVr9Ig2gKum3Zq_Wivv6zY)
#       └── folder_2_2 (1RKlsexA8h7NHvBAWRbU27MJotic7KXe3)
# ============================================================================


@dataclass
class ExpectedHierarchyNode:
    """Expected hierarchy node for test verification."""

    raw_node_id: str
    display_name: str
    node_type: HierarchyNodeType
    # None means parent is the source root (shared drive or my drive)
    raw_parent_id: str | None = None
    children: list["ExpectedHierarchyNode"] = field(default_factory=list)


# Expected hierarchy for shared_drive_1
EXPECTED_SHARED_DRIVE_1_HIERARCHY = ExpectedHierarchyNode(
    raw_node_id=SHARED_DRIVE_1_ID,
    display_name="Shared Drive 1",
    node_type=HierarchyNodeType.SHARED_DRIVE,
    raw_parent_id=None,
    children=[
        ExpectedHierarchyNode(
            raw_node_id=RESTRICTED_ACCESS_FOLDER_ID,
            display_name="restricted_access",
            node_type=HierarchyNodeType.FOLDER,
            raw_parent_id=SHARED_DRIVE_1_ID,
        ),
        ExpectedHierarchyNode(
            raw_node_id=FOLDER_1_ID,
            display_name="folder 1",
            node_type=HierarchyNodeType.FOLDER,
            raw_parent_id=SHARED_DRIVE_1_ID,
            children=[
                ExpectedHierarchyNode(
                    raw_node_id=FOLDER_1_1_ID,
                    display_name="folder 1-1",
                    node_type=HierarchyNodeType.FOLDER,
                    raw_parent_id=FOLDER_1_ID,
                ),
                ExpectedHierarchyNode(
                    raw_node_id=FOLDER_1_2_ID,
                    display_name="folder 1-2",
                    node_type=HierarchyNodeType.FOLDER,
                    raw_parent_id=FOLDER_1_ID,
                ),
            ],
        ),
    ],
)

# Expected hierarchy for shared_drive_2
EXPECTED_SHARED_DRIVE_2_HIERARCHY = ExpectedHierarchyNode(
    raw_node_id=SHARED_DRIVE_2_ID,
    display_name="Shared Drive 2",
    node_type=HierarchyNodeType.SHARED_DRIVE,
    raw_parent_id=None,
    children=[
        ExpectedHierarchyNode(
            raw_node_id=SECTIONS_FOLDER_ID,
            display_name="sections",
            node_type=HierarchyNodeType.FOLDER,
            raw_parent_id=SHARED_DRIVE_2_ID,
        ),
        ExpectedHierarchyNode(
            raw_node_id=FOLDER_2_ID,
            display_name="folder 2",
            node_type=HierarchyNodeType.FOLDER,
            raw_parent_id=SHARED_DRIVE_2_ID,
            children=[
                ExpectedHierarchyNode(
                    raw_node_id=FOLDER_2_1_ID,
                    display_name="folder 2-1",
                    node_type=HierarchyNodeType.FOLDER,
                    raw_parent_id=FOLDER_2_ID,
                ),
                ExpectedHierarchyNode(
                    raw_node_id=FOLDER_2_2_ID,
                    display_name="folder 2-2",
                    node_type=HierarchyNodeType.FOLDER,
                    raw_parent_id=FOLDER_2_ID,
                ),
            ],
        ),
    ],
)


def flatten_hierarchy(
    expected: ExpectedHierarchyNode,
) -> dict[str, ExpectedHierarchyNode]:
    """Flatten an expected hierarchy tree into a dict keyed by raw_node_id."""
    result = {expected.raw_node_id: expected}
    for child in expected.children:
        result.update(flatten_hierarchy(child))
    return result


def _node(
    raw_node_id: str,
    display_name: str,
    node_type: HierarchyNodeType,
    raw_parent_id: str | None = None,
) -> ExpectedHierarchyNode:
    return ExpectedHierarchyNode(
        raw_node_id=raw_node_id,
        display_name=display_name,
        node_type=node_type,
        raw_parent_id=raw_parent_id,
    )


# Flattened maps for easy lookup
EXPECTED_SHARED_DRIVE_1_NODES = flatten_hierarchy(EXPECTED_SHARED_DRIVE_1_HIERARCHY)
EXPECTED_SHARED_DRIVE_2_NODES = flatten_hierarchy(EXPECTED_SHARED_DRIVE_2_HIERARCHY)

EXTERNAL_SHARED_FOLDER_URL = (
    "https://drive.google.com/drive/folders/1sWC7Oi0aQGgifLiMnhTjvkhRWVeDa-XS"
)
EXTERNAL_SHARED_FOLDER_ID = "1sWC7Oi0aQGgifLiMnhTjvkhRWVeDa-XS"
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

# ============================================================================
# PERMISSION SYNC TEST DRIVES
# ============================================================================
# These are separate shared drives used specifically for testing permission sync.
# Each drive has different access levels:
#
# PERM_SYNC_DRIVE_ADMIN_ONLY: Only shared with admin
# PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A: Shared with admin and test_user_1
# PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B: Shared with admin and test_user_1
# ============================================================================

PERM_SYNC_DRIVE_ADMIN_ONLY_URL = (
    "https://drive.google.com/drive/folders/0ACOrCU1EMD1hUk9PVA"
)
PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_URL = (
    "https://drive.google.com/drive/folders/0ABec4pV29sMuUk9PVA"
)
PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_URL = (
    "https://drive.google.com/drive/folders/0ANpbToRgjHD4Uk9PVA"
)

PERM_SYNC_DRIVE_ADMIN_ONLY_ID = "0ACOrCU1EMD1hUk9PVA"
PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID = "0ABec4pV29sMuUk9PVA"
PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID = "0ANpbToRgjHD4Uk9PVA"

# ============================================================================
# ADDITIONAL DRIVES/FOLDERS ACCESSIBLE TO TEST_USER_1
# ============================================================================
# These are additional shared drives and folders that test_user_1 has access to.
# They are returned as hierarchy nodes when running the connector as test_user_1.
# ============================================================================

# Additional shared drives accessible to test_user_1
TEST_USER_1_MY_DRIVE_ID = "0AFpeuWG1VyABUk9PVA"  # My Drive indicator for test_user_1
TEST_USER_1_MY_DRIVE_FOLDER_ID = (
    "1tF10nDFND-GE_IT0f6PjEn2Du6m2k-DE"  # Child folder (partial sharing)
)

TEST_USER_1_DRIVE_B_ID = (
    "0AFskk4zfZm86Uk9PVA"  # My_super_special_shared_drive_suuuper_private
)
TEST_USER_1_DRIVE_B_FOLDER_ID = (
    "1oIj7nigzvP5xI2F8BmibUA8R_J3AbBA-"  # Child folder (silliness)
)

# Other drives test_user_1 has access to
TEST_USER_1_EXTRA_DRIVE_1_ID = "0AL67XRMq9reYUk9PVA"  # Okay_fine_admin_I_will_share
TEST_USER_1_EXTRA_DRIVE_2_ID = "0ACeKoHrGKxCbUk9PVA"  # reee test
TEST_USER_1_EXTRA_FOLDER_ID = (
    "1i2Q1TNvUfZkH-A7RGyAqRuEI-3mHANku"  # read only no download test
)

# Additional shared drives in the organization that appear when running include_all tests
ADMIN_MY_DRIVE_ID = "0ABTZwt798K7MUk9PVA"  # Admin's My Drive
TEST_USER_2_MY_DRIVE = "0ADjBZv2nEvJNUk9PVA"  # Test user 2's My Drive
TEST_USER_3_MY_DRIVE_ID = "0AKl0e4Wr5NW7Uk9PVA"  # Test user 3's My Drive
PILL_FOLDER_ID = "1FWzfA369tx9VT8scJ3LCOPBBuTBgt0OH"  # contains file with date pills

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

# Expected permissions for perm sync drives
# Maps drive ID -> set of user emails with access
PERM_SYNC_DRIVE_ACCESS_MAPPING: dict[str, set[str]] = {
    PERM_SYNC_DRIVE_ADMIN_ONLY_ID: {ADMIN_EMAIL},
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID: {ADMIN_EMAIL, TEST_USER_1_EMAIL},
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID: {ADMIN_EMAIL, TEST_USER_1_EMAIL},
}

# ============================================================================
# NON-SHARED-DRIVE HIERARCHY NODES
# ============================================================================
# These cover My Drive roots, perm sync drives, extra shared drives,
# and standalone folders that appear in various tests.
# Display names must match what the Google Drive API actually returns.
# ============================================================================

EXPECTED_FOLDER_3 = _node(
    FOLDER_3_ID, "Folder 3", HierarchyNodeType.FOLDER, ADMIN_MY_DRIVE_ID
)

EXPECTED_ADMIN_MY_DRIVE = _node(ADMIN_MY_DRIVE_ID, "My Drive", HierarchyNodeType.FOLDER)
EXPECTED_TEST_USER_1_MY_DRIVE = _node(
    TEST_USER_1_MY_DRIVE_ID, "My Drive", HierarchyNodeType.FOLDER
)
EXPECTED_TEST_USER_1_MY_DRIVE_FOLDER = _node(
    TEST_USER_1_MY_DRIVE_FOLDER_ID,
    "partial_sharing",
    HierarchyNodeType.FOLDER,
    TEST_USER_1_MY_DRIVE_ID,
)
EXPECTED_TEST_USER_2_MY_DRIVE = _node(
    TEST_USER_2_MY_DRIVE, "My Drive", HierarchyNodeType.FOLDER
)
EXPECTED_TEST_USER_3_MY_DRIVE = _node(
    TEST_USER_3_MY_DRIVE_ID, "My Drive", HierarchyNodeType.FOLDER
)

EXPECTED_PERM_SYNC_DRIVE_ADMIN_ONLY = _node(
    PERM_SYNC_DRIVE_ADMIN_ONLY_ID,
    "perm_sync_drive_0dc9d8b5-e243-4c2f-8678-2235958f7d7c",
    HierarchyNodeType.SHARED_DRIVE,
)
EXPECTED_PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A = _node(
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID,
    "perm_sync_drive_785db121-0823-4ebe-8689-ad7f52405e32",
    HierarchyNodeType.SHARED_DRIVE,
)
EXPECTED_PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B = _node(
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID,
    "perm_sync_drive_d8dc3649-3f65-4392-b87f-4b20e0389673",
    HierarchyNodeType.SHARED_DRIVE,
)

EXPECTED_TEST_USER_1_DRIVE_B = _node(
    TEST_USER_1_DRIVE_B_ID,
    "My_super_special_shared_drive_suuuper_private",
    HierarchyNodeType.SHARED_DRIVE,
)
EXPECTED_TEST_USER_1_DRIVE_B_FOLDER = _node(
    TEST_USER_1_DRIVE_B_FOLDER_ID,
    "silliness",
    HierarchyNodeType.FOLDER,
    TEST_USER_1_DRIVE_B_ID,
)
EXPECTED_TEST_USER_1_EXTRA_DRIVE_1 = _node(
    TEST_USER_1_EXTRA_DRIVE_1_ID,
    "Okay_Admin_fine_I_will_share",
    HierarchyNodeType.SHARED_DRIVE,
)
EXPECTED_TEST_USER_1_EXTRA_DRIVE_2 = _node(
    TEST_USER_1_EXTRA_DRIVE_2_ID, "reee test", HierarchyNodeType.SHARED_DRIVE
)
EXPECTED_TEST_USER_1_EXTRA_FOLDER = _node(
    TEST_USER_1_EXTRA_FOLDER_ID,
    "read only no download test",
    HierarchyNodeType.FOLDER,
)

EXPECTED_PILL_FOLDER = _node(
    PILL_FOLDER_ID, "pill_folder", HierarchyNodeType.FOLDER, ADMIN_MY_DRIVE_ID
)
EXPECTED_EXTERNAL_SHARED_FOLDER = _node(
    EXTERNAL_SHARED_FOLDER_ID, "Onyx-test", HierarchyNodeType.FOLDER
)

# Comprehensive mapping of ALL known hierarchy nodes.
# Every retrieved node is checked against this for display_name and node_type.
ALL_EXPECTED_HIERARCHY_NODES: dict[str, ExpectedHierarchyNode] = {
    **EXPECTED_SHARED_DRIVE_1_NODES,
    **EXPECTED_SHARED_DRIVE_2_NODES,
    FOLDER_3_ID: EXPECTED_FOLDER_3,
    ADMIN_MY_DRIVE_ID: EXPECTED_ADMIN_MY_DRIVE,
    TEST_USER_1_MY_DRIVE_ID: EXPECTED_TEST_USER_1_MY_DRIVE,
    TEST_USER_1_MY_DRIVE_FOLDER_ID: EXPECTED_TEST_USER_1_MY_DRIVE_FOLDER,
    TEST_USER_2_MY_DRIVE: EXPECTED_TEST_USER_2_MY_DRIVE,
    TEST_USER_3_MY_DRIVE_ID: EXPECTED_TEST_USER_3_MY_DRIVE,
    PERM_SYNC_DRIVE_ADMIN_ONLY_ID: EXPECTED_PERM_SYNC_DRIVE_ADMIN_ONLY,
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID: EXPECTED_PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A,
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID: EXPECTED_PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B,
    TEST_USER_1_DRIVE_B_ID: EXPECTED_TEST_USER_1_DRIVE_B,
    TEST_USER_1_DRIVE_B_FOLDER_ID: EXPECTED_TEST_USER_1_DRIVE_B_FOLDER,
    TEST_USER_1_EXTRA_DRIVE_1_ID: EXPECTED_TEST_USER_1_EXTRA_DRIVE_1,
    TEST_USER_1_EXTRA_DRIVE_2_ID: EXPECTED_TEST_USER_1_EXTRA_DRIVE_2,
    TEST_USER_1_EXTRA_FOLDER_ID: EXPECTED_TEST_USER_1_EXTRA_FOLDER,
    PILL_FOLDER_ID: EXPECTED_PILL_FOLDER,
    EXTERNAL_SHARED_FOLDER_ID: EXPECTED_EXTERNAL_SHARED_FOLDER,
}

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


def load_connector_outputs(
    connector: GoogleDriveConnector,
    include_permissions: bool = False,
) -> ConnectorOutput:
    """Load all documents, failures, and hierarchy nodes from the connector."""
    return load_all_from_connector(
        connector,
        0,
        time.time(),
        include_permissions=include_permissions,
    )


def assert_hierarchy_nodes_match_expected(
    retrieved_nodes: list[HierarchyNode],
    expected_nodes: dict[str, ExpectedHierarchyNode],
    ignorable_node_ids: set[str] | None = None,
) -> None:
    """
    Assert that retrieved hierarchy nodes match expected structure.

    Checks node IDs, display names, node types, and parent relationships
    for EVERY retrieved node (global checks).

    Args:
        retrieved_nodes: List of HierarchyNode objects from the connector
        expected_nodes: Dict mapping raw_node_id -> ExpectedHierarchyNode with
            expected display_name, node_type, and raw_parent_id
        ignorable_node_ids: Optional set of node IDs that can be missing or extra
            without failing. Useful for non-deterministically returned nodes.
    """
    expected_node_ids = set(expected_nodes.keys())
    retrieved_node_ids = {node.raw_node_id for node in retrieved_nodes}
    ignorable = ignorable_node_ids or set()

    missing = expected_node_ids - retrieved_node_ids - ignorable
    extra = retrieved_node_ids - expected_node_ids - ignorable

    if missing or extra:
        print("Expected hierarchy node IDs:")
        print(sorted(expected_node_ids))
        print("Retrieved hierarchy node IDs:")
        print(sorted(retrieved_node_ids))
        print("Extra (retrieved but not expected):")
        print(sorted(retrieved_node_ids - expected_node_ids))
        print("Missing (expected but not retrieved):")
        print(sorted(expected_node_ids - retrieved_node_ids))
        if ignorable:
            print("Ignorable node IDs:")
            print(sorted(ignorable))

    assert (
        not missing and not extra
    ), f"Hierarchy node mismatch. Missing: {missing}, Extra: {extra}"

    for node in retrieved_nodes:
        if node.raw_node_id in ignorable and node.raw_node_id not in expected_nodes:
            continue

        assert (
            node.raw_node_id in expected_nodes
        ), f"Node {node.raw_node_id} ({node.display_name}) not found in expected_nodes"
        expected = expected_nodes[node.raw_node_id]

        assert node.display_name == expected.display_name, (
            f"Display name mismatch for node {node.raw_node_id}: "
            f"expected '{expected.display_name}', got '{node.display_name}'"
        )
        assert node.node_type == expected.node_type, (
            f"Node type mismatch for node {node.raw_node_id}: "
            f"expected '{expected.node_type}', got '{node.node_type}'"
        )
        if expected.raw_parent_id is not None:
            assert node.raw_parent_id == expected.raw_parent_id, (
                f"Parent mismatch for node {node.raw_node_id} ({node.display_name}): "
                f"expected parent={expected.raw_parent_id}, got parent={node.raw_parent_id}"
            )


def _pick(
    *node_ids: str,
) -> dict[str, ExpectedHierarchyNode]:
    """Pick nodes from ALL_EXPECTED_HIERARCHY_NODES by their IDs."""
    return {nid: ALL_EXPECTED_HIERARCHY_NODES[nid] for nid in node_ids}


def _clear_parents(
    nodes: dict[str, ExpectedHierarchyNode],
    *node_ids: str,
) -> dict[str, ExpectedHierarchyNode]:
    """Return a shallow copy of nodes with the specified nodes' parents set to None.
    Useful for OAuth tests where the user can't resolve certain parents
    (e.g. a folder in another user's My Drive)."""
    result = dict(nodes)
    for nid in node_ids:
        result[nid] = replace(result[nid], raw_parent_id=None)
    return result


def get_expected_hierarchy_for_shared_drives(
    include_drive_1: bool = True,
    include_drive_2: bool = True,
    include_restricted_folder: bool = True,
) -> dict[str, ExpectedHierarchyNode]:
    """Get expected hierarchy nodes for shared drives."""
    result: dict[str, ExpectedHierarchyNode] = {}

    if include_drive_1:
        result.update(EXPECTED_SHARED_DRIVE_1_NODES)
        if not include_restricted_folder:
            result.pop(RESTRICTED_ACCESS_FOLDER_ID, None)

    if include_drive_2:
        result.update(EXPECTED_SHARED_DRIVE_2_NODES)

    return result


def get_expected_hierarchy_for_folder_1() -> dict[str, ExpectedHierarchyNode]:
    """Get expected hierarchy for folder_1 and its children only."""
    return _pick(FOLDER_1_ID, FOLDER_1_1_ID, FOLDER_1_2_ID)


def get_expected_hierarchy_for_folder_2() -> dict[str, ExpectedHierarchyNode]:
    """Get expected hierarchy for folder_2 and its children only."""
    return _pick(FOLDER_2_ID, FOLDER_2_1_ID, FOLDER_2_2_ID)


def get_expected_hierarchy_for_test_user_1() -> dict[str, ExpectedHierarchyNode]:
    """
    Get expected hierarchy for test_user_1's full access (OAuth).

    test_user_1 has access to:
    - shared_drive_1 and its contents (folder_1, folder_1_1, folder_1_2)
    - folder_3 (shared from admin's My Drive)
    - PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A and PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B
    - Additional drives/folders the user has access to

    NOTE: Folder 3 lives in the admin's My Drive. When running as an OAuth
    connector for test_user_1, the Google Drive API won't return the parent
    for Folder 3 because the user can't access the admin's My Drive root.
    """
    result = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=False,
        include_restricted_folder=False,
    )
    result.update(
        _pick(
            FOLDER_3_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID,
            TEST_USER_1_MY_DRIVE_ID,
            TEST_USER_1_MY_DRIVE_FOLDER_ID,
            TEST_USER_1_DRIVE_B_ID,
            TEST_USER_1_DRIVE_B_FOLDER_ID,
            TEST_USER_1_EXTRA_DRIVE_1_ID,
            TEST_USER_1_EXTRA_DRIVE_2_ID,
            TEST_USER_1_EXTRA_FOLDER_ID,
        )
    )
    return _clear_parents(result, FOLDER_3_ID)


def get_expected_hierarchy_for_test_user_1_shared_drives_only() -> (
    dict[str, ExpectedHierarchyNode]
):
    """Expected hierarchy nodes when test_user_1 runs with include_shared_drives=True only."""
    result = get_expected_hierarchy_for_test_user_1()
    for nid in (
        TEST_USER_1_MY_DRIVE_ID,
        TEST_USER_1_MY_DRIVE_FOLDER_ID,
        FOLDER_3_ID,
        TEST_USER_1_EXTRA_FOLDER_ID,
    ):
        result.pop(nid, None)
    return result


def get_expected_hierarchy_for_test_user_1_shared_with_me_only() -> (
    dict[str, ExpectedHierarchyNode]
):
    """Expected hierarchy nodes when test_user_1 runs with include_files_shared_with_me=True only."""
    return _clear_parents(
        _pick(FOLDER_3_ID, TEST_USER_1_EXTRA_FOLDER_ID),
        FOLDER_3_ID,
    )


def get_expected_hierarchy_for_test_user_1_my_drive_only() -> (
    dict[str, ExpectedHierarchyNode]
):
    """Expected hierarchy nodes when test_user_1 runs with include_my_drives=True only."""
    return _pick(TEST_USER_1_MY_DRIVE_ID, TEST_USER_1_MY_DRIVE_FOLDER_ID)
