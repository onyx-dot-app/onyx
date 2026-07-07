"""Drive "everyone at <domain>" shares must map to a derived domain group
(domain:<domain>), never to instance-public, on both the file and folder
permission paths, and the user-side ACL must carry the matching token derived
from the user's own email domain."""

from types import SimpleNamespace
from typing import Any
from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from ee.onyx.external_permissions.google_drive.doc_sync import (
    get_external_access_for_folder,
)
from ee.onyx.external_permissions.google_drive.doc_sync import (
    get_external_access_for_raw_gdrive_file,
)
from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from ee.onyx.external_permissions.google_drive.models import PermissionType
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.access.utils import prefix_external_group
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.db.models import User

COMPANY_DOMAIN = "companya.com"
OTHER_DOMAIN = "companyb.com"

# Never used: the file path takes inline permissions and the folder path's
# permission fetch is patched.
_DRIVE_SERVICE = cast(GoogleDriveService, SimpleNamespace())


def _raw_file(permissions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "doc-1", "permissions": permissions}


def _domain_permission(domain: str, perm_id: str = "perm-domain") -> dict[str, Any]:
    return {"id": perm_id, "type": "domain", "domain": domain}


def _file_access(
    permissions: list[dict[str, Any]], add_prefix: bool = False
) -> ExternalAccess:
    return get_external_access_for_raw_gdrive_file(
        file=_raw_file(permissions),
        company_domain=COMPANY_DOMAIN,
        retriever_drive_service=None,
        admin_drive_service=_DRIVE_SERVICE,
        fallback_user_email="admin@companya.com",
        add_prefix=add_prefix,
    )


def test_own_domain_share_is_domain_group_not_public() -> None:
    access = _file_access([_domain_permission(COMPANY_DOMAIN)])
    assert access.is_public is False
    assert f"domain:{COMPANY_DOMAIN}" in access.external_user_group_ids


def test_cross_company_domain_share_scopes_to_that_domain() -> None:
    access = _file_access([_domain_permission(OTHER_DOMAIN)])
    assert access.is_public is False
    assert f"domain:{OTHER_DOMAIN}" in access.external_user_group_ids
    assert f"domain:{COMPANY_DOMAIN}" not in access.external_user_group_ids


def test_domain_is_lowercased() -> None:
    access = _file_access([_domain_permission("CompanyA.COM")])
    assert f"domain:{COMPANY_DOMAIN}" in access.external_user_group_ids


def test_link_only_domain_share_grants_nothing() -> None:
    perm = {**_domain_permission(COMPANY_DOMAIN), "allowFileDiscovery": False}
    access = _file_access([perm])
    assert access.is_public is False
    assert not access.external_user_group_ids


def test_domain_permission_without_domain_grants_nothing() -> None:
    access = _file_access([{"id": "p1", "type": "domain"}])
    assert access.is_public is False
    assert not access.external_user_group_ids


def test_anyone_share_stays_public() -> None:
    access = _file_access([{"id": "p1", "type": "anyone"}])
    assert access.is_public is True


def test_user_and_group_shares_unchanged() -> None:
    access = _file_access(
        [
            {"id": "p1", "type": "user", "emailAddress": "bob@companyb.com"},
            {"id": "p2", "type": "group", "emailAddress": "eng@companya.com"},
        ]
    )
    assert access.is_public is False
    assert access.external_user_emails == {"bob@companyb.com"}
    assert "eng@companya.com" in access.external_user_group_ids


def test_indexing_path_prefixes_domain_group() -> None:
    access = _file_access([_domain_permission(COMPANY_DOMAIN)], add_prefix=True)
    expected = build_ext_group_name_for_onyx(
        f"domain:{COMPANY_DOMAIN}", DocumentSource.GOOGLE_DRIVE
    )
    assert expected in access.external_user_group_ids


def _folder_access(
    permissions: list[GoogleDrivePermission], add_prefix: bool = False
) -> ExternalAccess:
    with patch(
        "ee.onyx.external_permissions.google_drive.doc_sync.get_permissions_by_ids",
        return_value=permissions,
    ):
        return get_external_access_for_folder(
            folder={"id": "folder-1", "permissionIds": ["p1"]},
            google_domain=COMPANY_DOMAIN,
            drive_service=_DRIVE_SERVICE,
            add_prefix=add_prefix,
        )


def _folder_domain_permission(
    domain: str, allow_file_discovery: bool | None = True
) -> GoogleDrivePermission:
    return GoogleDrivePermission(
        id="p1",
        email_address=None,
        type=PermissionType.DOMAIN,
        domain=domain,
        permission_details=None,
        allow_file_discovery=allow_file_discovery,
    )


def test_folder_domain_share_is_domain_group_not_public() -> None:
    access = _folder_access([_folder_domain_permission(COMPANY_DOMAIN)])
    assert access.is_public is False
    assert f"domain:{COMPANY_DOMAIN}" in access.external_user_group_ids


def test_folder_link_only_domain_share_grants_nothing() -> None:
    access = _folder_access(
        [_folder_domain_permission(COMPANY_DOMAIN, allow_file_discovery=False)]
    )
    assert access.is_public is False
    assert not access.external_user_group_ids


def test_folder_anyone_link_only_stays_non_public() -> None:
    anyone = GoogleDrivePermission(
        id="p1",
        email_address=None,
        type=PermissionType.ANYONE,
        domain=None,
        permission_details=None,
        allow_file_discovery=False,
    )
    access = _folder_access([anyone])
    assert access.is_public is False


def test_user_acl_carries_own_domain_token() -> None:
    from ee.onyx.access.access import _get_acl_for_user

    user = cast(
        User, SimpleNamespace(id="u1", email="Alice@CompanyA.com", is_anonymous=False)
    )
    with (
        patch("ee.onyx.access.access.fetch_user_groups_for_user", return_value=[]),
        patch("ee.onyx.access.access.fetch_external_groups_for_user", return_value=[]),
        patch(
            "ee.onyx.access.access.get_acl_for_user_without_groups",
            return_value=set(),
        ),
    ):
        acl = _get_acl_for_user(user, db_session=cast(Session, None))

    expected = prefix_external_group(
        build_ext_group_name_for_onyx(
            f"domain:{COMPANY_DOMAIN}", DocumentSource.GOOGLE_DRIVE
        )
    )
    assert expected in acl


def test_anonymous_user_gets_no_domain_token() -> None:
    from ee.onyx.access.access import _get_acl_for_user

    user = cast(User, SimpleNamespace(id="u2", email="anon@x.com", is_anonymous=True))
    with patch(
        "ee.onyx.access.access.get_acl_for_user_without_groups",
        return_value={"PUBLIC"},
    ):
        acl = _get_acl_for_user(user, db_session=cast(Session, None))

    assert not any(entry.startswith("external_group:") for entry in acl)
