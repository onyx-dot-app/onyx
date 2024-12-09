import time
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from danswer.access.models import ExternalAccess
from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_utils.google_utils import execute_paginated_retrieval
from danswer.connectors.google_utils.resources import get_admin_service
from ee.danswer.external_permissions.google_drive.doc_sync import (
    _get_permissions_from_slim_doc,
)
from tests.daily.connectors.google_drive.consts_and_utils import ACCESS_MAPPING
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import file_name_template
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import print_discrepencies
from tests.daily.connectors.google_drive.consts_and_utils import PUBLIC_RANGE
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_2_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_3_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_3_FILE_IDS


def get_keys_available_to_user_from_access_map(
    user_email: str,
    group_map: dict[str, list[str]],
    access_map: dict[str, ExternalAccess],
) -> list[str]:
    """
    Extracts the names of the files available to the user from the access map
    through their own email or group memberships or public access
    """
    group_emails_for_user = []
    for group_email, user_in_group_email_list in group_map.items():
        if user_email in user_in_group_email_list:
            group_emails_for_user.append(group_email)

    accessible_file_names_for_user = []
    for file_name, external_access in access_map.items():
        if external_access.is_public:
            accessible_file_names_for_user.append(file_name)
        elif user_email in external_access.external_user_emails:
            accessible_file_names_for_user.append(file_name)
        elif any(
            group_email in external_access.external_user_group_ids
            for group_email in group_emails_for_user
        ):
            accessible_file_names_for_user.append(file_name)
    return accessible_file_names_for_user


def assert_correct_access_for_user(
    user_email: str,
    expected_access_ids: list[int],
    group_map: dict[str, list[str]],
    retrieved_access_map: dict[str, ExternalAccess],
) -> None:
    """
    compares the expected access range of the user to the keys available to the user
    retrieved from the source
    """
    retrieved_keys_available_to_user = get_keys_available_to_user_from_access_map(
        user_email, group_map, retrieved_access_map
    )
    retrieved_file_names = set(retrieved_keys_available_to_user)

    # Combine public and user-specific access IDs
    all_accessible_ids = expected_access_ids + PUBLIC_RANGE
    expected_file_names = {file_name_template.format(i) for i in all_accessible_ids}

    print_discrepencies(expected_file_names, retrieved_file_names)

    assert expected_file_names == retrieved_file_names


# This function is supposed to map to the group_sync.py file for the google drive connector
# TODO: Call it directly
def get_group_map(google_drive_connector: GoogleDriveConnector) -> dict[str, list[str]]:
    admin_service = get_admin_service(
        creds=google_drive_connector.creds,
        user_email=google_drive_connector.primary_admin_email,
    )

    group_map: dict[str, list[str]] = {}
    for group in execute_paginated_retrieval(
        admin_service.groups().list,
        list_key="groups",
        domain=google_drive_connector.google_domain,
        fields="groups(email)",
    ):
        # The id is the group email
        group_email = group["email"]

        # Gather group member emails
        group_member_emails: list[str] = []
        for member in execute_paginated_retrieval(
            admin_service.members().list,
            list_key="members",
            groupKey=group_email,
            fields="members(email)",
        ):
            group_member_emails.append(member["email"])
        group_map[group_email] = group_member_emails
    return group_map


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_all_permissions(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    google_drive_connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )

    access_map: dict[str, ExternalAccess] = {}
    found_file_names = set()
    for slim_doc_batch in google_drive_connector.retrieve_all_slim_documents(
        0, time.time()
    ):
        for slim_doc in slim_doc_batch:
            name = (slim_doc.perm_sync_data or {})["name"]
            access_map[name] = _get_permissions_from_slim_doc(
                google_drive_connector=google_drive_connector,
                slim_doc=slim_doc,
            )
            found_file_names.add(name)

    for file_name, external_access in access_map.items():
        print(file_name, external_access)

    expected_file_range = (
        ADMIN_FILE_IDS  # Admin's My Drive
        + ADMIN_FOLDER_3_FILE_IDS  # Admin's Folder 3
        + TEST_USER_1_FILE_IDS  # TEST_USER_1's My Drive
        + TEST_USER_2_FILE_IDS  # TEST_USER_2's My Drive
        + TEST_USER_3_FILE_IDS  # TEST_USER_3's My Drive
        + SHARED_DRIVE_1_FILE_IDS  # Shared Drive 1
        + FOLDER_1_FILE_IDS  # Folder 1
        + FOLDER_1_1_FILE_IDS  # Folder 1_1
        + FOLDER_1_2_FILE_IDS  # Folder 1_2
        + SHARED_DRIVE_2_FILE_IDS  # Shared Drive 2
        + FOLDER_2_FILE_IDS  # Folder 2
        + FOLDER_2_1_FILE_IDS  # Folder 2_1
        + FOLDER_2_2_FILE_IDS  # Folder 2_2
        + SECTIONS_FILE_IDS  # Sections
    )
    expected_file_names = {
        file_name_template.format(file_id) for file_id in expected_file_range
    }

    # Should get everything
    print_discrepencies(expected_file_names, found_file_names)
    assert expected_file_names == found_file_names

    group_map = get_group_map(google_drive_connector)

    print("groups:\n", group_map)

    assert_correct_access_for_user(
        user_email=ADMIN_EMAIL,
        expected_access_ids=ACCESS_MAPPING[ADMIN_EMAIL],
        group_map=group_map,
        retrieved_access_map=access_map,
    )
    assert_correct_access_for_user(
        user_email=TEST_USER_1_EMAIL,
        expected_access_ids=ACCESS_MAPPING[TEST_USER_1_EMAIL],
        group_map=group_map,
        retrieved_access_map=access_map,
    )

    assert_correct_access_for_user(
        user_email=TEST_USER_2_EMAIL,
        expected_access_ids=ACCESS_MAPPING[TEST_USER_2_EMAIL],
        group_map=group_map,
        retrieved_access_map=access_map,
    )
    assert_correct_access_for_user(
        user_email=TEST_USER_3_EMAIL,
        expected_access_ids=ACCESS_MAPPING[TEST_USER_3_EMAIL],
        group_map=group_map,
        retrieved_access_map=access_map,
    )
