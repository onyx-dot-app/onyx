import time
from collections.abc import Generator
from functools import cached_property

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.gmail.models import GroupViewSetting
from ee.onyx.external_permissions.models import SyncEntityFailure
from ee.onyx.external_permissions.utils import (
    MAX_FAILED_ENTITY_FRACTION,
    credential_json,
)
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.gmail.collaborative_inbox import (
    COLLABORATIVE_INBOX_FIELD,
    GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE,
    build_groups_settings_service,
    get_group_members,
    has_collaborative_inbox,
    read_group_settings,
)
from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.gmail.models import GroupMembers, GroupRole
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
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

_VIEW_SETTING_FIELD = "whoCanViewGroup"
_GROUP_SETTINGS_FIELDS = f"{COLLABORATIVE_INBOX_FIELD},{_VIEW_SETTING_FIELD}"
# The Admin SDK alias for the calling admin's Workspace account. Unlike a domain
# filter it covers every domain in the account, as ALL_IN_DOMAIN_CAN_VIEW does.
_OWN_ACCOUNT = "my_customer"
# The most users the Admin SDK returns in one users.list page.
_MAX_USERS_PER_PAGE = 500
_OWNERS = frozenset({GroupRole.OWNER})
_OWNERS_AND_MANAGERS = frozenset({GroupRole.OWNER, GroupRole.MANAGER})


class _SyncDeadlineExceeded(TimeoutError):
    """Listing one large group or account can outlast the timeout, which the
    sync task checks only between yielded groups."""


def _check_sync_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise _SyncDeadlineExceeded(
            f"Gmail group sync exceeded {PERMISSION_SYNC_TIMEOUT}s before it finished"
        )


class _AccountUsers:
    """Every user of the Workspace account, listed at most once a sync."""

    def __init__(self, admin_service: AdminService, deadline: float) -> None:
        self._admin_service = admin_service
        self._deadline = deadline

    @cached_property
    def emails(self) -> frozenset[str]:
        user_emails: set[str] = set()
        for user in execute_paginated_retrieval(
            retrieval_function=self._admin_service.users().list,  # ty: ignore[unresolved-attribute]
            list_key="users",
            customer=_OWN_ACCOUNT,
            maxResults=_MAX_USERS_PER_PAGE,
            fields=USER_FIELDS,
        ):
            _check_sync_deadline(self._deadline)
            if user_email := user.get("primaryEmail"):
                user_emails.add(user_email.lower())
        return frozenset(user_emails)


def _get_view_setting(
    settings_service: GroupsSettingsService, group_email: str
) -> GroupViewSetting | None:
    """None when nobody reads the group's mail: the address stopped being a
    Collaborative Inbox group, or Google sent a view setting this enum lacks."""
    settings = read_group_settings(
        settings_service, group_email, _GROUP_SETTINGS_FIELDS
    )
    if settings is None or not has_collaborative_inbox(settings):
        logger.warning(
            "%s is not a Collaborative Inbox group, so nobody reads its mail",
            group_email,
        )
        return None

    view_setting = settings.get(_VIEW_SETTING_FIELD)
    try:
        return GroupViewSetting(view_setting)
    except ValueError:
        logger.warning(
            "%s has the unknown view setting %r, so nobody reads its mail",
            group_email,
            view_setting,
        )
        return None


def _with_account_users(
    members: GroupMembers, account_users: _AccountUsers
) -> frozenset[str]:
    if not members.has_all_account_users:
        return members.user_emails
    return members.user_emails | account_users.emails


def _get_member_reader_emails(
    admin_service: AdminService, group_email: str, account_users: _AccountUsers
) -> frozenset[str]:
    direct_members = get_group_members(
        admin_service, group_email, include_nested_groups=False
    )
    all_members = get_group_members(
        admin_service, group_email, include_nested_groups=True
    )
    reader_emails = _with_account_users(direct_members, account_users)
    # Google does not deliver the group's mail to a nested member from outside
    # the account, so such a member does not read it here either.
    nested_only_emails = all_members.user_emails - direct_members.user_emails
    if nested_only_emails:
        reader_emails |= nested_only_emails & account_users.emails
    return reader_emails


def _get_reader_emails(
    settings_service: GroupsSettingsService,
    admin_service: AdminService,
    group_email: str,
    account_users: _AccountUsers,
) -> frozenset[str]:
    match _get_view_setting(settings_service, group_email):
        case None:
            return frozenset()
        case GroupViewSetting.ALL_OWNERS_CAN_VIEW:
            # Members of a nested group that holds the role are left out.
            return _with_account_users(
                get_group_members(
                    admin_service,
                    group_email,
                    include_nested_groups=False,
                    roles=_OWNERS,
                ),
                account_users,
            )
        case GroupViewSetting.ALL_MANAGERS_CAN_VIEW:
            return _with_account_users(
                get_group_members(
                    admin_service,
                    group_email,
                    include_nested_groups=False,
                    roles=_OWNERS_AND_MANAGERS,
                ),
                account_users,
            )
        case GroupViewSetting.ALL_MEMBERS_CAN_VIEW:
            return _get_member_reader_emails(admin_service, group_email, account_users)
        # A group open to the web gets the readers of an account-wide one, not
        # public access in Onyx.
        case GroupViewSetting.ALL_IN_DOMAIN_CAN_VIEW | GroupViewSetting.ANYONE_CAN_VIEW:
            return account_users.emails


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
    # A missing scope is a setup error the admin must fix, so fail the whole sync.
    if settings_service is None:
        raise InsufficientPermissionsError(GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE)
    admin_service = get_google_service(
        GoogleService.ADMIN, gmail_connector.creds, gmail_connector.primary_admin_email
    )

    deadline = time.monotonic() + PERMISSION_SYNC_TIMEOUT
    account_users = _AccountUsers(admin_service, deadline)
    failed_group_count = 0
    for group_email in group_emails:
        _check_sync_deadline(deadline)
        try:
            reader_emails = _get_reader_emails(
                settings_service, admin_service, group_email, account_users
            )
        except _SyncDeadlineExceeded:
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
