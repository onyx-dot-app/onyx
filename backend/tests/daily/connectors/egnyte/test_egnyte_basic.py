"""Daily tests against the Egnyte test domain.

The tests read the fixed corpus under /Shared/OnyxPermTest that README.md next
to this file describes. Egnyte gives each access token 1,000 calls per day, so
the tests read only small folders and one run makes about 50 calls.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
import requests

from ee.onyx.connectors.perm_sync_valid import validate_egnyte_perm_sync
from ee.onyx.external_permissions.egnyte.access import (
    ADMINISTRATORS_GROUP_NAME,
    custom_group_id,
    default_group_id,
)
from ee.onyx.external_permissions.egnyte.group_sync import egnyte_groups
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.egnyte import connector as egnyte_connector_module
from onyx.connectors.egnyte.connector import OAUTH_SCOPES, EgnyteConnector
from onyx.connectors.egnyte.models import EgnyteUserType
from onyx.connectors.models import Document, HierarchyNode, SlimDocument
from onyx.utils.variable_functionality import global_version
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

DOMAIN = "app4danswer"
ROOT = "/Shared/OnyxPermTest"
TEST_GROUP_NAME = "OnyxTestGroup"
STANDARD_USER_1 = "onyx_std1"
STANDARD_USER_2 = "onyx_std2"
POWER_USER = "chris_1_power"
TEST_USERS = frozenset({STANDARD_USER_1, STANDARD_USER_2, POWER_USER})
BIG_FILE_COUNT = 120
# Small enough that the Big folder takes several pages.
TEST_PAGE_SIZE = 50
RENAME_FOLDER = "Versions"
RENAMED_FOLDER = "Versions Renamed"

# Each folder's readers among the test users and groups, besides the
# administrators, who read every folder.
EXPECTED_READERS: dict[str, tuple[set[str], set[str]]] = {
    "OnyxPermTest": ({STANDARD_USER_1}, {TEST_GROUP_NAME}),
    "Inherits": ({STANDARD_USER_1}, {TEST_GROUP_NAME}),
    "InheritsPlusOwn": ({STANDARD_USER_1, POWER_USER}, {TEST_GROUP_NAME}),
    # A user's None does not remove the user's group grant.
    "Override": (set(), {TEST_GROUP_NAME}),
    "NoInherit": ({POWER_USER}, set()),
    "Deep": ({STANDARD_USER_2}, set()),
    "DefaultGroups": (
        {STANDARD_USER_1, STANDARD_USER_2},
        {
            TEST_GROUP_NAME,
            "All Power Users",
            "All Standard Users",
            "All Standard Users and Power Users",
        },
    ),
    "Versions": ({STANDARD_USER_1}, {TEST_GROUP_NAME}),
    "Big": ({STANDARD_USER_1}, {TEST_GROUP_NAME}),
}

pytestmark = pytest.mark.secrets(
    TestSecret.EGNYTE_CLIENT_ID,
    TestSecret.EGNYTE_CLIENT_SECRET,
    TestSecret.EGNYTE_TEST_USERNAME,
    TestSecret.EGNYTE_TEST_PASSWORD,
)


@pytest.fixture(scope="module")
def access_token(test_secrets: dict[TestSecret, str]) -> str:
    response = requests.post(
        f"https://{DOMAIN}.egnyte.com/puboauth/token",
        data={
            "grant_type": "password",
            "client_id": test_secrets[TestSecret.EGNYTE_CLIENT_ID],
            "client_secret": test_secrets[TestSecret.EGNYTE_CLIENT_SECRET],
            "username": test_secrets[TestSecret.EGNYTE_TEST_USERNAME],
            "password": test_secrets[TestSecret.EGNYTE_TEST_PASSWORD],
            "scope": OAUTH_SCOPES,
        },
        timeout=30,
    )
    # The error body carries no token, and the request body is not shown.
    assert response.ok, f"Egnyte token request failed: HTTP {response.status_code}"
    return response.json()["access_token"]


def _connector(access_token: str, folder_path: str) -> EgnyteConnector:
    connector = EgnyteConnector(folder_path=folder_path)
    connector.load_credentials({"domain": DOMAIN, "access_token": access_token})
    return connector


@pytest.fixture
def ee_enabled() -> Generator[None, None, None]:
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    yield
    if not was_ee:
        global_version.unset_ee()


@pytest.fixture
def small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(egnyte_connector_module, "FOLDER_PAGE_SIZE", TEST_PAGE_SIZE)
    monkeypatch.setattr(egnyte_connector_module, "_PAGE_OVERLAP", TEST_PAGE_SIZE // 10)


def _text(document: Document) -> str:
    return " ".join(section.text for section in document.sections if section.text)


def _emails_by_username(connector: EgnyteConnector) -> dict[str, str]:
    return {
        user.user_name: user.email.strip().lower()
        for user in connector.ops.list_users()
    }


def _administrator_emails(connector: EgnyteConnector) -> set[str]:
    return {
        user.email.strip().lower()
        for user in connector.ops.list_users()
        if user.active and user.user_type == EgnyteUserType.ADMIN
    }


def _move(access_token: str, source: str, destination: str) -> None:
    response = requests.post(
        f"https://{DOMAIN}.egnyte.com/pubapi/v1/fs{quote(source)}",
        json={"action": "move", "destination": destination},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    assert response.ok, f"Moving {source} failed: HTTP {response.status_code}"


def test_index_without_permissions(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    access_token: str,
) -> None:
    result = load_all_from_connector(
        _connector(access_token, f"{ROOT}/Versions"), 0, 2**31
    )

    assert [node.display_name for node in result.hierarchy_nodes] == ["Versions"]
    assert [(d.semantic_identifier, _text(d)) for d in result.documents] == [
        ("doc.txt", "Version two of the doc.")
    ]
    assert result.documents[0].external_access is None


def test_index_with_permissions(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    ee_enabled: None,  # noqa: ARG001
    access_token: str,
) -> None:
    connector = _connector(access_token, f"{ROOT}/NoInherit")
    emails = _emails_by_username(connector)

    result = load_all_from_connector(connector, 0, 2**31, include_permissions=True)

    assert {_text(d) for d in result.documents} == {
        "Test note in /NoInherit.",
        "Test note in /NoInherit/Deep.",
    }
    for document in result.documents:
        access = document.external_access
        assert access is not None
        assert access.external_user_group_ids == {
            build_ext_group_name_for_onyx(
                default_group_id(DOMAIN, ADMINISTRATORS_GROUP_NAME),
                DocumentSource.EGNYTE,
            )
        }
        expected_user = STANDARD_USER_2 if "Deep." in _text(document) else POWER_USER
        assert emails[expected_user] in access.external_user_emails
    assert {node.display_name for node in result.hierarchy_nodes} == {
        "NoInherit",
        "Deep",
    }


def test_folder_permissions_match_egnyte(
    ee_enabled: None,  # noqa: ARG001
    small_pages: None,  # noqa: ARG001
    access_token: str,
) -> None:
    connector = _connector(access_token, ROOT)
    validate_egnyte_perm_sync(connector)
    emails = _emails_by_username(connector)
    administrators = _administrator_emails(connector)
    test_emails = {emails[username] for username in TEST_USERS}
    group_ids = {group.display_name: group.id for group in connector.ops.list_groups()}

    def expected_access(folder_name: str) -> tuple[set[str], set[str]]:
        users, groups = EXPECTED_READERS[folder_name]
        bare_group_ids = {default_group_id(DOMAIN, ADMINISTRATORS_GROUP_NAME)} | {
            custom_group_id(DOMAIN, group_ids[group])
            if group in group_ids
            else default_group_id(DOMAIN, group)
            for group in groups
        }
        return {emails[user] for user in users}, bare_group_ids

    def actual_access(access: ExternalAccess | None) -> tuple[set[str], set[str]]:
        assert access is not None and not access.is_public
        assert administrators <= access.external_user_emails
        return access.external_user_emails & test_emails, set(
            access.external_user_group_ids
        )

    items = [
        item for batch in connector.retrieve_all_slim_docs_perm_sync() for item in batch
    ]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    documents = [item for item in items if isinstance(item, SlimDocument)]

    folder_names = {node.raw_node_id: node.display_name for node in nodes}
    assert set(folder_names.values()) == set(EXPECTED_READERS)
    for node in nodes:
        users, groups = expected_access(node.display_name)
        prefixed = {
            build_ext_group_name_for_onyx(group, DocumentSource.EGNYTE)
            for group in groups
        }
        assert actual_access(node.external_access) == (users, prefixed), (
            node.display_name
        )

    assert len({document.id for document in documents}) == len(documents)
    big_file_count = 0
    for document in documents:
        assert document.parent_hierarchy_raw_node_id is not None
        folder_name = folder_names[document.parent_hierarchy_raw_node_id]
        assert actual_access(document.external_access) == expected_access(
            folder_name
        ), folder_name
        big_file_count += folder_name == "Big"
    assert big_file_count == BIG_FILE_COUNT


def test_group_sync(
    ee_enabled: None,  # noqa: ARG001
    access_token: str,
) -> None:
    connector = _connector(access_token, ROOT)
    emails = _emails_by_username(connector)
    group_ids = {group.display_name: group.id for group in connector.ops.list_groups()}

    groups = {
        group.id: set(group.user_emails) & {emails[u] for u in TEST_USERS}
        for group in egnyte_groups(connector)
    }

    assert groups[custom_group_id(DOMAIN, group_ids[TEST_GROUP_NAME])] == {
        emails[STANDARD_USER_1],
        emails[POWER_USER],
    }
    assert groups[default_group_id(DOMAIN, "All Standard Users")] == {
        emails[STANDARD_USER_1],
        emails[STANDARD_USER_2],
    }
    assert groups[default_group_id(DOMAIN, "All Power Users")] == {emails[POWER_USER]}
    assert groups[default_group_id(DOMAIN, ADMINISTRATORS_GROUP_NAME)] == set()


def test_ids_survive_a_folder_rename(access_token: str) -> None:
    def ids(folder_path: str) -> set[str]:
        connector = _connector(access_token, folder_path)
        return {
            item.id if isinstance(item, SlimDocument) else item.raw_node_id
            for batch in connector.retrieve_all_slim_docs()
            for item in batch
        }

    before = ids(f"{ROOT}/{RENAME_FOLDER}")
    _move(access_token, f"{ROOT}/{RENAME_FOLDER}", f"{ROOT}/{RENAMED_FOLDER}")
    try:
        after = ids(f"{ROOT}/{RENAMED_FOLDER}")
    finally:
        _move(access_token, f"{ROOT}/{RENAMED_FOLDER}", f"{ROOT}/{RENAME_FOLDER}")

    assert len(before) == 2
    assert after == before
