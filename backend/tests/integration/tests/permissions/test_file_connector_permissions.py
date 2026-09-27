"""Integration tests for file-connector file-management permissions.

The file CRUD routes (``/manage/admin/connector/file/upload``,
``/manage/admin/connector/{id}/files``,
``/manage/admin/connector/{id}/files/update``) are gated by
``require_permission(Permission.MANAGE_CONNECTORS)`` plus
``_fetch_and_check_file_connector_cc_pair_permissions``.

This test verifies that a user granted ``manage:connectors`` via a
non-default user group can manage files on a public file cc-pair they did
not create — the new-model replacement for the old ``GLOBAL_CURATOR``
coverage.
"""

import os

import pytest

from onyx.db.enums import AccessType, Permission
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.user import DATestUser, UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


def _create_connector_managers_group(
    *,
    admin_user: DATestUser,
    group_user: DATestUser,
    name: str,
) -> None:
    """Create a non-default group that grants its members manage:connectors.

    User effective permissions are recomputed synchronously when group
    permissions are set, so this does not need to wait for the slower document
    index user-group sync marker.
    """
    group = UserGroupManager.create(
        name=name,
        user_ids=[group_user.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    set_perms_response = UserGroupManager.set_permissions(
        user_group=group,
        permissions=[Permission.MANAGE_CONNECTORS.value],
        user_performing_action=admin_user,
    )
    set_perms_response.raise_for_status()


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User-group permission tests are enterprise only",
)
@pytest.mark.usefixtures("reset")
def test_manage_connectors_user_can_edit_public_file_connector() -> None:
    """A non-admin user whose group grants manage:connectors can list AND
    update files on a PUBLIC file cc-pair they don't own."""
    admin_user = UserManager.create(name="admin_user")

    editor = UserManager.create(name="file_editor")
    _create_connector_managers_group(
        admin_user=admin_user, group_user=editor, name="file_managers"
    )

    # Admin owns a public file connector + cc-pair
    upload = FileManager.upload_connector_file(
        "initial-file.txt", b"initial file content", admin_user
    )
    initial_file_id, initial_file_name = upload.file_paths[0], upload.file_names[0]
    connector = ConnectorManager.create(
        user_performing_action=admin_user,
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
        user_performing_action=admin_user,
        source=DocumentSource.FILE,
        curator_public=True,
        groups=[],
        name="public_file_connector_credential",
    )
    CCPairManager.create(
        connector_id=connector.id,
        credential_id=credential.id,
        user_performing_action=admin_user,
        access_type=AccessType.PUBLIC,
        groups=[],
        name="public_file_connector_cc_pair",
    )

    # Editor can list files even without owning the cc-pair
    list_response = FileManager.list_connector_files(connector.id, editor)
    list_response.raise_for_status()
    assert any(f["file_id"] == initial_file_id for f in list_response.json()["files"])

    # Editor can update files on the public cc-pair — `_add_user_filters`
    # returns the cc-pair lookup unfiltered for any user holding
    # MANAGE_CONNECTORS (see onyx/db/connector_credential_pair.py:55).
    update_response = FileManager.update_connector_files(
        connector.id,
        editor,
        file_ids_to_remove=[initial_file_id],
        files=[("editor-file.txt", b"editor updated file")],
    )
    update_response.raise_for_status()
    payload = update_response.json()
    assert initial_file_id not in payload["file_paths"]
    assert "editor-file.txt" in payload["file_names"]
