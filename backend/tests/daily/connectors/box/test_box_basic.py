"""Daily tests against a real Box enterprise.

The expected corpus (folder tree, collaborations, shared links, group) is
defined in README.md next to this file — set the test enterprise up exactly as
described there before running.
"""

from datetime import timezone
from time import time
from typing import cast
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.box.group_sync import box_group_sync
from onyx.connectors.box.connector import box_all_enterprise_users_group_id
from onyx.connectors.box.connector import box_group_id
from onyx.connectors.box.connector import BOX_ROOT_FOLDER_ID
from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.models import ConnectorCredentialPair
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

TEST_FOLDER_NAME = "Onyx Connector Test Folder"

# The corpus exercises multiple share levels for the collaborator user:
#   - Shared Folder (folder-level VIEWER)      -> shared.txt is readable
#   - editor_doc.txt (file-level EDITOR)        -> readable
#   - Uploader Folder (folder-level UPLOADER)   -> uploader_doc.txt NOT readable
#     (uploader is upload-only; the connector must not grant it read access)
#   - public_doc.txt (open shared link)         -> public
#   - root_doc.txt (no share)                   -> owner-only
ROOT_DOC_NAME = "root_doc.txt"
ROOT_DOC_CONTENT = "box root doc for onyx connector tests"
ALPHA_DOC_NAME = "alpha.txt"
ALPHA_DOC_CONTENT = "alpha doc for onyx connector tests"
SHARED_DOC_NAME = "shared.txt"
SHARED_DOC_CONTENT = "shared doc for onyx connector tests"
PUBLIC_DOC_NAME = "public_doc.txt"
PUBLIC_DOC_CONTENT = "public doc for onyx connector tests"
EDITOR_DOC_NAME = "editor_doc.txt"
EDITOR_DOC_CONTENT = "editor doc for onyx connector tests"
UPLOADER_DOC_NAME = "uploader_doc.txt"
UPLOADER_DOC_CONTENT = "uploader doc for onyx connector tests"

SUBFOLDER_A_NAME = "Subfolder A"
SHARED_FOLDER_NAME = "Shared Folder"
UPLOADER_FOLDER_NAME = "Uploader Folder"

# A Box web link (bookmark) in the root test folder. Indexed only when
# include_web_links is enabled; its "content" is just name + description.
WEB_LINK_NAME = "Onyx Example Link"
WEB_LINK_URL = "https://www.onyx.app"
WEB_LINK_DESCRIPTION = "example bookmark for onyx connector tests"

TEST_GROUP_NAME = "Onyx Test Group"

EXPECTED_DOC_NAMES = {
    ROOT_DOC_NAME,
    ALPHA_DOC_NAME,
    SHARED_DOC_NAME,
    PUBLIC_DOC_NAME,
    EDITOR_DOC_NAME,
    UPLOADER_DOC_NAME,
}

EXPECTED_FOLDER_NAMES = {
    TEST_FOLDER_NAME,
    SUBFOLDER_A_NAME,
    SHARED_FOLDER_NAME,
    UPLOADER_FOLDER_NAME,
}

pytestmark = pytest.mark.secrets(
    TestSecret.BOX_CLIENT_ID,
    TestSecret.BOX_CLIENT_SECRET,
    TestSecret.BOX_ENTERPRISE_ID,
    TestSecret.BOX_USER_EMAIL,
    TestSecret.BOX_COLLABORATOR_EMAIL,
)


def _credentials(test_secrets: dict[TestSecret, str]) -> dict[str, str]:
    return {
        "box_client_id": test_secrets[TestSecret.BOX_CLIENT_ID],
        "box_client_secret": test_secrets[TestSecret.BOX_CLIENT_SECRET],
        "box_enterprise_id": test_secrets[TestSecret.BOX_ENTERPRISE_ID],
        "box_user_email": test_secrets[TestSecret.BOX_USER_EMAIL],
    }


def _find_test_folder_id(test_secrets: dict[TestSecret, str]) -> str:
    probe = BoxConnector()
    probe.load_credentials(_credentials(test_secrets))
    items = probe.content_client.folders.get_folder_items(
        BOX_ROOT_FOLDER_ID, fields=["type", "id", "name"], usemarker=True, limit=1000
    )
    for item in items.entries or []:
        if item.name == TEST_FOLDER_NAME:
            return item.id
    raise AssertionError(
        f"Test folder {TEST_FOLDER_NAME!r} not found in the Box root of the "
        "impersonated user. Set up the corpus per "
        "backend/tests/daily/connectors/box/README.md"
    )


@pytest.fixture
def box_connector(test_secrets: dict[TestSecret, str]) -> BoxConnector:
    connector = BoxConnector(
        folder_ids=[_find_test_folder_id(test_secrets)], include_web_links=False
    )
    connector.load_credentials(_credentials(test_secrets))
    return connector


def test_load_documents(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    box_connector: BoxConnector,
) -> None:
    result = load_all_from_connector(box_connector, 0, time())

    documents_by_name = {d.semantic_identifier: d for d in result.documents}
    assert set(documents_by_name) == EXPECTED_DOC_NAMES

    node_names = {n.display_name for n in result.hierarchy_nodes}
    assert node_names == EXPECTED_FOLDER_NAMES

    def _text_of(doc: Document) -> str:
        return " ".join(s.text for s in doc.sections if s.text).strip()

    assert _text_of(documents_by_name[ROOT_DOC_NAME]) == ROOT_DOC_CONTENT
    assert _text_of(documents_by_name[ALPHA_DOC_NAME]) == ALPHA_DOC_CONTENT
    assert _text_of(documents_by_name[SHARED_DOC_NAME]) == SHARED_DOC_CONTENT
    assert _text_of(documents_by_name[PUBLIC_DOC_NAME]) == PUBLIC_DOC_CONTENT
    assert _text_of(documents_by_name[EDITOR_DOC_NAME]) == EDITOR_DOC_CONTENT
    assert _text_of(documents_by_name[UPLOADER_DOC_NAME]) == UPLOADER_DOC_CONTENT

    assert documents_by_name[ROOT_DOC_NAME].metadata["path"] == TEST_FOLDER_NAME
    assert (
        documents_by_name[ALPHA_DOC_NAME].metadata["path"]
        == f"{TEST_FOLDER_NAME}/{SUBFOLDER_A_NAME}"
    )
    assert (
        documents_by_name[SHARED_DOC_NAME].metadata["path"]
        == f"{TEST_FOLDER_NAME}/{SHARED_FOLDER_NAME}"
    )
    assert (
        documents_by_name[UPLOADER_DOC_NAME].metadata["path"]
        == f"{TEST_FOLDER_NAME}/{UPLOADER_FOLDER_NAME}"
    )

    owner_login = box_connector.content_client.users.get_user_me().login
    for document in result.documents:
        assert document.id.startswith("box-file-")
        assert document.doc_updated_at is not None
        assert document.doc_updated_at.tzinfo == timezone.utc
        assert document.doc_created_at is not None
        assert document.doc_created_at.tzinfo == timezone.utc
        assert document.primary_owners is not None
        assert document.primary_owners[0].email == owner_login

        section = document.sections[0]
        assert section.link is not None
        assert section.link.startswith("https://app.box.com/file/")


def test_web_links(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    # web links are indexed only when include_web_links is enabled, as a thin
    # "bookmark" document: name + description as text, section linking to the
    # target URL (the linked page's content is NOT fetched).
    connector = BoxConnector(
        folder_ids=[_find_test_folder_id(test_secrets)], include_web_links=True
    )
    connector.load_credentials(_credentials(test_secrets))
    result = load_all_from_connector(connector, 0, time())

    documents_by_name = {d.semantic_identifier: d for d in result.documents}
    # the files are still indexed, plus the bookmark
    assert EXPECTED_DOC_NAMES <= set(documents_by_name)
    assert WEB_LINK_NAME in documents_by_name

    web_link = documents_by_name[WEB_LINK_NAME]
    assert web_link.id.startswith("box-weblink-")
    assert web_link.metadata["path"] == TEST_FOLDER_NAME
    section = web_link.sections[0]
    assert isinstance(section, TextSection)
    assert section.link == WEB_LINK_URL
    assert WEB_LINK_DESCRIPTION in (section.text or "")


def test_poll_window_filters_documents_but_not_hierarchy(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    box_connector: BoxConnector,
) -> None:
    # A 1970 window can never contain any real Box file.
    result = load_all_from_connector(box_connector, 0, 1_000_000)
    assert result.documents == []
    # The folder tree is time-independent and must still be yielded.
    assert {n.display_name for n in result.hierarchy_nodes} == EXPECTED_FOLDER_NAMES


@pytest.mark.usefixtures("enable_ee")
def test_perm_sync_external_access(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    box_connector: BoxConnector,
    test_secrets: dict[TestSecret, str],
) -> None:
    collaborator_email = test_secrets[TestSecret.BOX_COLLABORATOR_EMAIL]
    result = load_all_from_connector(box_connector, 0, time(), include_permissions=True)
    documents_by_name = {d.semantic_identifier: d for d in result.documents}
    assert set(documents_by_name) == EXPECTED_DOC_NAMES

    # folder-level VIEWER collaboration -> collaborator can read
    shared_access = documents_by_name[SHARED_DOC_NAME].external_access
    assert shared_access is not None
    assert collaborator_email in shared_access.external_user_emails
    assert shared_access.is_public is False

    # file-level EDITOR collaboration -> collaborator can read
    editor_access = documents_by_name[EDITOR_DOC_NAME].external_access
    assert editor_access is not None
    assert collaborator_email in editor_access.external_user_emails
    assert editor_access.is_public is False

    # folder-level UPLOADER collaboration -> upload-only, NOT read access.
    # The document is still indexed (the owner can read it), but the
    # collaborator must be absent from its access set.
    uploader_access = documents_by_name[UPLOADER_DOC_NAME].external_access
    assert uploader_access is not None
    assert collaborator_email not in uploader_access.external_user_emails
    assert uploader_access.external_user_emails, "owner should still have access"
    assert uploader_access.is_public is False

    # no collaboration, no shared link -> owner-only
    root_access = documents_by_name[ROOT_DOC_NAME].external_access
    assert root_access is not None
    assert collaborator_email not in root_access.external_user_emails
    assert root_access.is_public is False

    # open shared link -> public
    public_access = documents_by_name[PUBLIC_DOC_NAME].external_access
    assert public_access is not None
    assert public_access.is_public is True

    # every document must carry externally-resolved access in perm-sync mode
    for document in result.documents:
        assert document.external_access is not None

    # folder nodes carry access too; the shared folder grants the collaborator
    shared_folder_node = next(
        n for n in result.hierarchy_nodes if n.display_name == SHARED_FOLDER_NAME
    )
    assert shared_folder_node.external_access is not None
    assert collaborator_email in shared_folder_node.external_access.external_user_emails


def _mock_cc_pair(
    test_secrets: dict[TestSecret, str], folder_id: str
) -> ConnectorCredentialPair:
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.id = 1
    cc_pair.connector = MagicMock()
    cc_pair.connector.connector_specific_config = {"folder_ids": [folder_id]}
    cc_pair.connector.indexing_start = None
    cc_pair.credential = MagicMock()
    cc_pair.credential.credential_json = MagicMock()
    cc_pair.credential.credential_json.get_value.return_value = _credentials(
        test_secrets
    )
    return cast(ConnectorCredentialPair, cc_pair)


def test_group_sync(test_secrets: dict[TestSecret, str]) -> None:
    folder_id = _find_test_folder_id(test_secrets)
    collaborator_email = test_secrets[TestSecret.BOX_COLLABORATOR_EMAIL]

    groups = list(box_group_sync("tenant", _mock_cc_pair(test_secrets, folder_id)))
    groups_by_id = {g.id: g for g in groups}

    # the synthetic enterprise-wide group backs "company" shared links and
    # must contain every managed user, including the collaborator
    enterprise_group_id = box_all_enterprise_users_group_id(
        test_secrets[TestSecret.BOX_ENTERPRISE_ID]
    )
    assert enterprise_group_id in groups_by_id
    enterprise_group = groups_by_id[enterprise_group_id]
    assert collaborator_email in enterprise_group.user_emails

    # the real Box group from the test corpus, with its membership expanded
    connector = BoxConnector()
    connector.load_credentials(_credentials(test_secrets))
    box_groups = connector.enterprise_client.groups.get_groups(limit=1000)
    test_group = next(
        (g for g in (box_groups.entries or []) if g.name == TEST_GROUP_NAME), None
    )
    assert test_group is not None, (
        f"Box group {TEST_GROUP_NAME!r} not found; set up the corpus per "
        "backend/tests/daily/connectors/box/README.md"
    )
    assert box_group_id(test_group.id) in groups_by_id
    assert collaborator_email in groups_by_id[box_group_id(test_group.id)].user_emails


def test_validate_connector_settings(test_secrets: dict[TestSecret, str]) -> None:
    valid = BoxConnector(folder_ids=[_find_test_folder_id(test_secrets)])
    valid.load_credentials(_credentials(test_secrets))
    valid.validate_connector_settings()
    valid.probe_group_listing_permission()

    missing_folder = BoxConnector(folder_ids=["999999999999999"])
    missing_folder.load_credentials(_credentials(test_secrets))
    with pytest.raises(ConnectorValidationError):
        missing_folder.validate_connector_settings()
