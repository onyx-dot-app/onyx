"""Drive "everyone at <domain>" shares must map to a domain group
(domain:<domain>), never to instance-public, on both the file and folder
permission paths. The user-side token comes from the synced domain group's real
Workspace membership, not from the user's email string."""

import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, call, patch

from sqlalchemy.orm import Session

from ee.onyx.external_permissions.google_drive.doc_sync import (
    get_external_access_for_folder,
    get_external_access_for_raw_gdrive_file,
)
from ee.onyx.external_permissions.google_drive.models import (
    GoogleDrivePermission,
    PermissionType,
)
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx, prefix_external_group
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.db.models import User

COMPANY_DOMAIN = "companya.com"
OTHER_DOMAIN = "companyb.com"
RETRIEVER_EMAIL = f"retriever@{COMPANY_DOMAIN}"
OWNER_EMAIL = f"owner@{COMPANY_DOMAIN}"
ADMIN_EMAIL = f"admin@{COMPANY_DOMAIN}"


def _mock_ops() -> GoogleDriveSourceOperations:
    # Tests take inline permissions or patch the permission fetch, so no
    # gateway operation runs.
    return MagicMock(spec=GoogleDriveSourceOperations)


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
        ops=_mock_ops(),
        retriever_email=None,
        admin_email=ADMIN_EMAIL,
        fallback_user_email=ADMIN_EMAIL,
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


def _retriever_user_permission() -> GoogleDrivePermission:
    return GoogleDrivePermission(
        id="p1",
        email_address=RETRIEVER_EMAIL,
        type=PermissionType.USER,
        domain=None,
        permission_details=None,
        allow_file_discovery=None,
    )


def test_retries_incomplete_owner_permissions_as_retriever() -> None:
    ops = _mock_ops()

    with patch(
        "ee.onyx.external_permissions.google_drive.doc_sync.get_permissions_by_ids",
        side_effect=[[], [_retriever_user_permission()]],
    ) as mock_get_permissions:
        access = get_external_access_for_raw_gdrive_file(
            file={"id": "doc-1", "permissionIds": ["p1"]},
            company_domain=COMPANY_DOMAIN,
            ops=ops,
            retriever_email=OWNER_EMAIL,
            admin_email=ADMIN_EMAIL,
            fallback_user_email=RETRIEVER_EMAIL,
            fallback_retriever_email=RETRIEVER_EMAIL,
        )

    assert access.external_user_emails == {RETRIEVER_EMAIL}
    assert mock_get_permissions.call_args_list == [
        call(
            ops=ops,
            user_email=OWNER_EMAIL,
            doc_id="doc-1",
            permission_ids=["p1"],
        ),
        call(
            ops=ops,
            user_email=RETRIEVER_EMAIL,
            doc_id="doc-1",
            permission_ids=["p1"],
        ),
    ]


def test_retriever_impersonation_failure_falls_back_to_admin() -> None:
    ops = _mock_ops()
    refresh_error = GoogleDriveRefreshError("unauthorized")

    with (
        patch(
            "ee.onyx.external_permissions.google_drive.doc_sync.get_permissions_by_ids",
            side_effect=[[], refresh_error, [_retriever_user_permission()]],
        ) as mock_get_permissions,
        patch(
            "ee.onyx.external_permissions.google_drive.doc_sync.logger.warning"
        ) as mock_warning,
    ):
        access = get_external_access_for_raw_gdrive_file(
            file={"id": "doc-1", "permissionIds": ["p1"]},
            company_domain=COMPANY_DOMAIN,
            ops=ops,
            retriever_email=OWNER_EMAIL,
            admin_email=ADMIN_EMAIL,
            fallback_user_email=RETRIEVER_EMAIL,
            fallback_retriever_email=RETRIEVER_EMAIL,
        )

    assert access.external_user_emails == {RETRIEVER_EMAIL}
    assert mock_get_permissions.call_args_list == [
        call(
            ops=ops,
            user_email=OWNER_EMAIL,
            doc_id="doc-1",
            permission_ids=["p1"],
        ),
        call(
            ops=ops,
            user_email=RETRIEVER_EMAIL,
            doc_id="doc-1",
            permission_ids=["p1"],
        ),
        call(
            ops=ops,
            user_email=ADMIN_EMAIL,
            doc_id="doc-1",
            permission_ids=["p1"],
        ),
    ]
    mock_warning.assert_called_once_with(
        "Could not impersonate non-admin user for document %s: %s",
        "doc-1",
        refresh_error,
    )


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
            ops=_mock_ops(),
            user_email=ADMIN_EMAIL,
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


def test_user_acl_carries_synced_domain_group() -> None:
    from ee.onyx.access.access import _get_acl_for_user

    user = cast(
        User, SimpleNamespace(id="u1", email="Alice@CompanyA.com", is_anonymous=False)
    )
    domain_group = build_ext_group_name_for_onyx(
        f"domain:{COMPANY_DOMAIN}", DocumentSource.GOOGLE_DRIVE
    )
    with (
        patch("ee.onyx.access.access.fetch_user_groups_for_user", return_value=[]),
        patch(
            "ee.onyx.access.access.fetch_external_groups_for_user",
            return_value=[SimpleNamespace(external_user_group_id=domain_group)],
        ),
        patch(
            "ee.onyx.access.access.get_acl_for_user_without_groups",
            return_value=set(),
        ),
    ):
        acl = _get_acl_for_user(user, db_session=cast(Session, None))

    assert prefix_external_group(domain_group) in acl


def test_user_acl_has_no_domain_token_without_synced_membership() -> None:
    # A user's email domain alone must not grant the domain group. Membership
    # comes only from the synced group, so a user Google never placed in the
    # Workspace gets nothing even if their email string matches.
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

    assert not any(entry.startswith("external_group:") for entry in acl)


def test_anonymous_user_gets_no_domain_token() -> None:
    from ee.onyx.access.access import _get_acl_for_user

    user = cast(User, SimpleNamespace(id="u2", email="anon@x.com", is_anonymous=True))
    with patch(
        "ee.onyx.access.access.get_acl_for_user_without_groups",
        return_value={"PUBLIC"},
    ):
        acl = _get_acl_for_user(user, db_session=cast(Session, None))

    assert not any(entry.startswith("external_group:") for entry in acl)


def test_group_sync_domain_group_uses_real_roster() -> None:
    from ee.onyx.external_permissions.google_drive import group_sync

    ops = MagicMock(spec=GoogleDriveSourceOperations)
    # The gateway drops directory rows without a primaryEmail.
    ops.list_user_emails.return_value = iter(
        ["alice@companya.com", "bob@companya.com", "alice@companya.com"]
    )
    members = group_sync._get_all_domain_users(ops, deadline=time.monotonic() + 60)

    assert sorted(members) == ["alice@companya.com", "bob@companya.com"]
    ops.list_user_emails.assert_called_once_with()
