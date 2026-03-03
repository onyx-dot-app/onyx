import io
import json
import os

import pytest
import requests

from onyx.db.enums import AccessType
from onyx.db.models import UserRole
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import DATestUser
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


def _upload_connector_file(
    *,
    user_performing_action: DATestUser,
    file_name: str,
    content: bytes,
) -> tuple[str, str]:
    headers = user_performing_action.headers.copy()
    headers.pop("Content-Type", None)

    response = requests.post(
        f"{API_SERVER_URL}/manage/admin/connector/file/upload",
        files=[("files", (file_name, io.BytesIO(content), "text/plain"))],
        headers=headers,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["file_paths"][0], payload["file_names"][0]


def _update_connector_files(
    *,
    connector_id: int,
    user_performing_action: DATestUser,
    file_ids_to_remove: list[str],
    new_file_name: str,
    new_file_content: bytes,
) -> requests.Response:
    headers = user_performing_action.headers.copy()
    headers.pop("Content-Type", None)

    return requests.post(
        f"{API_SERVER_URL}/manage/admin/connector/{connector_id}/files/update",
        data={"file_ids_to_remove": json.dumps(file_ids_to_remove)},
        files=[("files", (new_file_name, io.BytesIO(new_file_content), "text/plain"))],
        headers=headers,
    )


def _list_connector_files(
    *,
    connector_id: int,
    user_performing_action: DATestUser,
) -> requests.Response:
    return requests.get(
        f"{API_SERVER_URL}/manage/admin/connector/{connector_id}/files",
        headers=user_performing_action.headers,
    )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Curator and user group tests are enterprise only",
)
def test_only_global_curator_can_update_public_file_connector_files(
    reset: None,
) -> None:
    _ = reset
    admin_user = UserManager.create(name="admin_user")

    global_curator_creator = UserManager.create(name="global_curator_creator")
    global_curator_creator = UserManager.set_role(
        user_to_set=global_curator_creator,
        target_role=UserRole.GLOBAL_CURATOR,
        user_performing_action=admin_user,
    )

    global_curator_editor = UserManager.create(name="global_curator_editor")
    global_curator_editor = UserManager.set_role(
        user_to_set=global_curator_editor,
        target_role=UserRole.GLOBAL_CURATOR,
        user_performing_action=admin_user,
    )

    curator_user = UserManager.create(name="curator_user")
    curator_group = UserGroupManager.create(
        name="curator_group",
        user_ids=[curator_user.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[curator_group],
        user_performing_action=admin_user,
    )
    UserGroupManager.set_curator_status(
        test_user_group=curator_group,
        user_to_set_as_curator=curator_user,
        user_performing_action=admin_user,
    )

    initial_file_id, initial_file_name = _upload_connector_file(
        user_performing_action=global_curator_creator,
        file_name="initial-file.txt",
        content=b"initial file content",
    )

    connector = ConnectorManager.create(
        user_performing_action=global_curator_creator,
        name="public_file_connector",
        source=DocumentSource.FILE,
        connector_specific_config={
            "file_locations": [initial_file_id],
            "file_names": [initial_file_name],
            "zip_metadata_file_id": None,
        },
        access_type=AccessType.PUBLIC,
        groups=[],
    )
    credential = CredentialManager.create(
        user_performing_action=global_curator_creator,
        source=DocumentSource.FILE,
        curator_public=True,
        groups=[],
        name="public_file_connector_credential",
    )
    CCPairManager.create(
        connector_id=connector.id,
        credential_id=credential.id,
        user_performing_action=global_curator_creator,
        access_type=AccessType.PUBLIC,
        groups=[],
        name="public_file_connector_cc_pair",
    )

    curator_list_response = _list_connector_files(
        connector_id=connector.id,
        user_performing_action=curator_user,
    )
    curator_list_response.raise_for_status()
    curator_list_payload = curator_list_response.json()
    assert any(f["file_id"] == initial_file_id for f in curator_list_payload["files"])

    global_curator_list_response = _list_connector_files(
        connector_id=connector.id,
        user_performing_action=global_curator_editor,
    )
    global_curator_list_response.raise_for_status()
    global_curator_list_payload = global_curator_list_response.json()
    assert any(
        f["file_id"] == initial_file_id for f in global_curator_list_payload["files"]
    )

    denied_response = _update_connector_files(
        connector_id=connector.id,
        user_performing_action=curator_user,
        file_ids_to_remove=[initial_file_id],
        new_file_name="curator-file.txt",
        new_file_content=b"curator updated file",
    )
    assert denied_response.status_code == 403

    allowed_response = _update_connector_files(
        connector_id=connector.id,
        user_performing_action=global_curator_editor,
        file_ids_to_remove=[initial_file_id],
        new_file_name="global-curator-file.txt",
        new_file_content=b"global curator updated file",
    )
    allowed_response.raise_for_status()

    payload = allowed_response.json()
    assert initial_file_id not in payload["file_paths"]
    assert "global-curator-file.txt" in payload["file_names"]
