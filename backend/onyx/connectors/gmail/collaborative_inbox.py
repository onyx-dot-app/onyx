import re
from collections.abc import Callable
from functools import cached_property
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

from onyx.connectors.gmail.models import GroupMembers, GroupRole
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval,
    execute_single_retrieval,
)
from onyx.connectors.google_utils.resources import (
    AdminService,
    GoogleService,
    GroupsSettingsService,
    get_google_service,
    get_impersonated_creds,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.utils.logger import setup_logger

logger = setup_logger()

GROUPS_SETTINGS_SCOPE = "https://www.googleapis.com/auth/apps.groups.settings"
GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE = (
    "Collaborative Inbox groups need a service account whose domain-wide "
    f"delegation grants the scope {GROUPS_SETTINGS_SCOPE}."
)

COLLABORATIVE_INBOX_FIELD = "enableCollaborativeInbox"
_GROUP_MEMBER_FIELDS = "nextPageToken, members(email, role, type)"
_USER_MEMBER_TYPE = "USER"
# Every user of the Workspace account, as one member.
_ACCOUNT_MEMBER_TYPE = "CUSTOMER"
# Upper bound on the member addresses held for one group. An address measures
# about 125 bytes in the set, so this holds it near 60 MB.
_MAX_GROUP_MEMBERS = 500_000
# A List-ID value is an optional phrase, then the id in angle brackets.
_LIST_ID_RE = re.compile(r"<([^<>\s]+)>\s*$")


def build_groups_settings_service(
    creds: ServiceAccountCredentials | OAuthCredentials, primary_admin_email: str
) -> GroupsSettingsService | None:
    """A Groups Settings client that acts as the primary admin. None when the
    credential cannot get the Groups settings scope."""
    # Onyx's OAuth consent does not request this scope.
    if not isinstance(creds, ServiceAccountCredentials):
        return None

    # Requested alone: Google rejects a whole token request when domain-wide
    # delegation lacks one of its scopes.
    settings_creds = creds.with_scopes([GROUPS_SETTINGS_SCOPE])
    try:
        get_impersonated_creds(settings_creds, primary_admin_email).refresh(Request())
    except RefreshError as e:
        if MISSING_SCOPES_ERROR_STR not in str(e):
            raise
        return None

    return get_google_service(
        GoogleService.GROUPS_SETTINGS, settings_creds, primary_admin_email
    )


def read_group_settings(
    settings_service: GroupsSettingsService, group_email: str, fields: str
) -> dict[str, str] | None:
    """The `fields` of the group's settings. None when the address is not a
    group."""
    try:
        return next(
            execute_single_retrieval(
                retrieval_function=settings_service.groups().get,  # ty: ignore[unresolved-attribute]
                groupUniqueId=group_email,
                fields=fields,
            )
        )
    except HttpError as e:
        # A 403 is not an answer. Read as "not a group", it would empty the
        # slim listing, and pruning would delete the group's documents.
        if e.resp.status not in (400, 404):
            raise
        logger.warning("%s is not a group: %s", group_email, e)
        return None


def has_collaborative_inbox(settings: dict[str, str]) -> bool:
    # The Groups Settings API returns booleans as strings.
    return settings.get(COLLABORATIVE_INBOX_FIELD) == "true"


def is_collaborative_inbox(
    settings_service: GroupsSettingsService, group_email: str
) -> bool:
    settings = read_group_settings(
        settings_service, group_email, COLLABORATIVE_INBOX_FIELD
    )
    return settings is not None and has_collaborative_inbox(settings)


def get_group_members(
    admin_service: AdminService,
    group_email: str,
    include_nested_groups: bool,
    roles: frozenset[GroupRole] | None = None,
    check_deadline: Callable[[], None] | None = None,
) -> GroupMembers:
    """The users in the group, and those of its nested groups when asked. With
    `roles`, only the members that hold one of them. `check_deadline` runs for
    each member and raises to stop a listing that takes too long."""
    list_kwargs: dict[str, Any] = {}
    if roles is not None:
        list_kwargs["roles"] = ",".join(sorted(role.value for role in roles))

    user_emails: set[str] = set()
    has_all_account_users = False
    for member in execute_paginated_retrieval(
        retrieval_function=admin_service.members().list,  # ty: ignore[unresolved-attribute]
        list_key="members",
        groupKey=group_email,
        includeDerivedMembership=include_nested_groups,
        fields=_GROUP_MEMBER_FIELDS,
        **list_kwargs,
    ):
        if check_deadline is not None:
            check_deadline()
        if roles is not None and member.get("role") not in roles:
            continue
        member_email = member.get("email")
        if member.get("type") == _ACCOUNT_MEMBER_TYPE:
            has_all_account_users = True
        elif member.get("type") == _USER_MEMBER_TYPE and member_email:
            user_emails.add(member_email.lower())
            if len(user_emails) > _MAX_GROUP_MEMBERS:
                raise RuntimeError(
                    f"{group_email} has more than {_MAX_GROUP_MEMBERS} members"
                )
    return GroupMembers(
        user_emails=frozenset(user_emails),
        has_all_account_users=has_all_account_users,
    )


def _header_values(message: dict[str, Any], name: str) -> list[str]:
    return [
        header.get("value", "")
        for header in message.get("payload", {}).get("headers", [])
        if header.get("name", "").lower() == name
    ]


def get_rfc_message_id(message: dict[str, Any]) -> str | None:
    """The Message-ID header without its angle brackets. Unlike the Gmail
    message id, it is the same in every mailbox's copy."""
    for value in _header_values(message, "message-id"):
        if rfc_message_id := value.strip().strip("<>"):
            return rfc_message_id
    return None


def get_delivering_group(
    message: dict[str, Any], group_emails: frozenset[str]
) -> str | None:
    """Which of the lowercase `group_emails` delivered this copy. Google Groups
    puts the group's address in X-BeenThere and its dotted form in List-ID. The
    dotted form alone is ambiguous: a.b@example.com and a@b.example.com share it."""
    list_ids = {
        match.group(1).lower()
        for value in _header_values(message, "list-id")
        if (match := _LIST_ID_RE.search(value))
    }
    for value in _header_values(message, "x-beenthere"):
        group_email = value.strip().lower()
        if group_email in group_emails and group_email.replace("@", ".") in list_ids:
            return group_email
    return None


class CollaborativeInboxLookup:
    """Tells which of the connector's Collaborative Inbox groups delivered a
    mailbox's copy of a message. It reads each group's settings and members
    once and keeps them for the run."""

    def __init__(
        self,
        creds: ServiceAccountCredentials | OAuthCredentials,
        primary_admin_email: str,
        group_emails: list[str],
    ) -> None:
        self._creds = creds
        self._primary_admin_email = primary_admin_email
        self._group_emails = frozenset(email.lower() for email in group_emails)
        # None when the address is not a Collaborative Inbox group, or when the
        # credential cannot read group settings.
        self._members_by_group: dict[str, GroupMembers | None] = {}

    @cached_property
    def _settings_service(self) -> GroupsSettingsService | None:
        return build_groups_settings_service(self._creds, self._primary_admin_email)

    @cached_property
    def _admin_service(self) -> AdminService:
        return get_google_service(
            GoogleService.ADMIN, self._creds, self._primary_admin_email
        )

    def has_settings_access(self) -> bool:
        return self._settings_service is not None

    def get_group(self, message: dict[str, Any], mailbox_email: str) -> str | None:
        """The Collaborative Inbox group that delivered this copy of the
        message, when the mailbox belongs to the group. Any sender can set the
        headers, so they alone do not make a copy group mail."""
        if not self._group_emails:
            return None
        group_email = get_delivering_group(message, self._group_emails)
        if group_email is None:
            return None
        return group_email if self._is_member(group_email, mailbox_email) else None

    def get_groups_of_member(self, mailbox_email: str) -> list[str]:
        return [
            group_email
            for group_email in sorted(self._group_emails)
            if self._is_member(group_email, mailbox_email)
        ]

    def get_groups_without_collaborative_inbox(self) -> list[str]:
        return [
            group_email
            for group_email in sorted(self._group_emails)
            if self._get_members(group_email) is None
        ]

    def _is_member(self, group_email: str, mailbox_email: str) -> bool:
        members = self._get_members(group_email)
        if members is None:
            return False
        # The connector reads only the mailboxes of the account's own users.
        return (
            members.has_all_account_users
            or mailbox_email.lower() in members.user_emails
        )

    def _get_members(self, group_email: str) -> GroupMembers | None:
        if group_email not in self._members_by_group:
            self._members_by_group[group_email] = self._read_members(group_email)
        return self._members_by_group[group_email]

    def _read_members(self, group_email: str) -> GroupMembers | None:
        if self._settings_service is None:
            return None
        if not is_collaborative_inbox(self._settings_service, group_email):
            return None
        return get_group_members(
            self._admin_service, group_email, include_nested_groups=True
        )
