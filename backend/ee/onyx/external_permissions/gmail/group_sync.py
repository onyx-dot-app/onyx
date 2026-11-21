"""The readers of the Gmail connector's Collaborative Inbox groups. A group
document names its group, and each group maps to the people that the group's
"who can view conversations" setting allows."""

import time
from collections.abc import Generator, Iterator

from googleapiclient.errors import HttpError

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.gmail.models import (
    GroupRole,
    GroupSettings,
    GroupViewSetting,
)
from ee.onyx.external_permissions.models import SyncEntityFailure
from ee.onyx.external_permissions.utils import (
    MAX_FAILED_ENTITY_FRACTION,
    credential_json,
)
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.gmail.collaborative_inbox import (
    GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE,
    build_groups_settings_service,
    list_group_member_emails,
)
from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval,
    execute_single_retrieval,
)
from onyx.connectors.google_utils.resources import (
    AdminService,
    GoogleService,
    GroupsSettingsService,
    get_google_service,
)
from onyx.connectors.google_utils.shared_constants import USER_FIELDS
from onyx.db.enums import SyncEntityKind
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_GROUP_SETTINGS_FIELDS = "enableCollaborativeInbox,whoCanViewGroup"
_DIRECT_MEMBER_FIELDS = "nextPageToken, members(email, role, type)"
_USER_MEMBER_TYPE = "USER"
# The Admin SDK alias for the Workspace account of the calling admin.
_OWN_ACCOUNT = "my_customer"
_ROLES_THAT_VIEW: dict[GroupViewSetting, frozenset[GroupRole]] = {
    GroupViewSetting.ALL_OWNERS_CAN_VIEW: frozenset({GroupRole.OWNER}),
    GroupViewSetting.ALL_MANAGERS_CAN_VIEW: frozenset(
        {GroupRole.OWNER, GroupRole.MANAGER}
    ),
}
# A group open to anyone on the web is read by the Workspace account, no wider.
_ACCOUNT_WIDE_VIEW_SETTINGS = frozenset(
    {GroupViewSetting.ANYONE_CAN_VIEW, GroupViewSetting.ALL_IN_DOMAIN_CAN_VIEW}
)


def _check_sync_deadline(deadline: float) -> None:
    """The caller checks its timeout only between yielded groups, and one
    large group or account can take longer than that to list."""
    if time.monotonic() > deadline:
        raise TimeoutError(
            f"Gmail group sync exceeded {PERMISSION_SYNC_TIMEOUT}s before it finished"
        )


def _get_group_settings(
    settings_service: GroupsSettingsService, group_email: str
) -> GroupSettings | None:
    """None for an address that is no longer a group."""
    try:
        settings = next(
            execute_single_retrieval(
                retrieval_function=settings_service.groups().get,  # ty: ignore[unresolved-attribute]
                groupUniqueId=group_email,
                fields=_GROUP_SETTINGS_FIELDS,
            )
        )
    except HttpError as e:
        if e.resp.status != 404:
            raise
        return None

    try:
        who_can_view = GroupViewSetting(settings.get("whoCanViewGroup"))
    except ValueError:
        who_can_view = None
    return GroupSettings(
        # The Groups Settings API returns booleans as strings.
        is_collaborative_inbox=settings.get("enableCollaborativeInbox") == "true",
        who_can_view=who_can_view,
    )


def _list_direct_member_emails(
    admin_service: AdminService, group_email: str, roles: frozenset[GroupRole]
) -> Iterator[str]:
    """The users who hold one of `roles` in the group itself. A nested group
    that holds the role grants its members nothing here."""
    for member in execute_paginated_retrieval(
        retrieval_function=admin_service.members().list,  # ty: ignore[unresolved-attribute]
        list_key="members",
        groupKey=group_email,
        fields=_DIRECT_MEMBER_FIELDS,
    ):
        member_email = member.get("email")
        if (
            member.get("type") == _USER_MEMBER_TYPE
            and member.get("role") in roles
            and member_email
        ):
            yield member_email.lower()


def _list_account_user_emails(admin_service: AdminService) -> Iterator[str]:
    for user in execute_paginated_retrieval(
        retrieval_function=admin_service.users().list,  # ty: ignore[unresolved-attribute]
        list_key="users",
        customer=_OWN_ACCOUNT,
        fields=USER_FIELDS,
    ):
        if user_email := user.get("primaryEmail"):
            yield user_email.lower()


def _list_reader_emails(
    settings_service: GroupsSettingsService,
    admin_service: AdminService,
    group_email: str,
) -> Iterator[str]:
    settings = _get_group_settings(settings_service, group_email)
    if settings is None or not settings.is_collaborative_inbox:
        logger.warning(
            "%s is not a Collaborative Inbox group, so nobody reads its mail",
            group_email,
        )
        return
    if settings.who_can_view is None:
        logger.warning(
            "%s has an unknown view setting, so nobody reads its mail", group_email
        )
        return

    if settings.who_can_view in _ACCOUNT_WIDE_VIEW_SETTINGS:
        yield from _list_account_user_emails(admin_service)
    elif settings.who_can_view == GroupViewSetting.ALL_MEMBERS_CAN_VIEW:
        yield from list_group_member_emails(admin_service, group_email)
    else:
        yield from _list_direct_member_emails(
            admin_service, group_email, _ROLES_THAT_VIEW[settings.who_can_view]
        )


def gmail_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup | SyncEntityFailure, None, None]:
    gmail_connector = GmailConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    group_emails = gmail_connector.collaborative_inbox_groups
    if not group_emails:
        return

    gmail_connector.load_credentials(credential_json(cc_pair))
    settings_service = build_groups_settings_service(
        gmail_connector.creds, gmail_connector.primary_admin_email
    )
    # Without the scope every group would sync as empty and hide its mail
    # with no error.
    if settings_service is None:
        raise InsufficientPermissionsError(GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE)
    admin_service = get_google_service(
        GoogleService.ADMIN, gmail_connector.creds, gmail_connector.primary_admin_email
    )

    deadline = time.monotonic() + PERMISSION_SYNC_TIMEOUT
    failed_group_count = 0
    for group_email in group_emails:
        reader_emails: set[str] = set()
        try:
            for reader_email in _list_reader_emails(
                settings_service, admin_service, group_email
            ):
                _check_sync_deadline(deadline)
                reader_emails.add(reader_email)
        except TimeoutError:
            raise
        except Exception as e:
            logger.exception("Could not read the readers of %s", group_email)
            failed_group_count += 1
            yield SyncEntityFailure(
                kind=SyncEntityKind.GROUP, id=group_email, message=str(e)
            )
            if failed_group_count > MAX_FAILED_ENTITY_FRACTION * len(group_emails):
                raise RuntimeError(
                    "Too many groups failed during the Gmail group sync"
                ) from e
            continue
        yield ExternalUserGroup(id=group_email, user_emails=sorted(reader_emails))
