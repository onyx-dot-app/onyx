import re
from collections.abc import Iterator
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

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

_COLLABORATIVE_INBOX_FIELD = "enableCollaborativeInbox"
_GROUP_MEMBER_FIELDS = "nextPageToken, members(email, type)"
_USER_MEMBER_TYPE = "USER"
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


def is_collaborative_inbox(
    settings_service: GroupsSettingsService, group_email: str
) -> bool:
    """Whether the address is a group with Collaborative Inbox turned on. False
    when it is not a group, or the credential cannot read its settings."""
    try:
        settings = next(
            execute_single_retrieval(
                retrieval_function=settings_service.groups().get,  # ty: ignore[unresolved-attribute]
                groupUniqueId=group_email,
                fields=_COLLABORATIVE_INBOX_FIELD,
            )
        )
    except HttpError as e:
        if e.resp.status not in (400, 403, 404):
            raise
        logger.warning("Could not read the group settings of %s: %s", group_email, e)
        return False
    # The Groups Settings API returns booleans as strings.
    return settings.get(_COLLABORATIVE_INBOX_FIELD) == "true"


def list_group_member_emails(
    admin_service: AdminService, group_email: str
) -> Iterator[str]:
    """The lowercased addresses of the users in the group, direct or through a
    nested group."""
    for member in execute_paginated_retrieval(
        retrieval_function=admin_service.members().list,  # ty: ignore[unresolved-attribute]
        list_key="members",
        groupKey=group_email,
        includeDerivedMembership=True,
        fields=_GROUP_MEMBER_FIELDS,
    ):
        member_email = member.get("email")
        if member.get("type") == _USER_MEMBER_TYPE and member_email:
            yield member_email.lower()


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
        self._group_emails = frozenset(group_emails)
        self._settings_service: GroupsSettingsService | None = None
        self._is_settings_service_built = False
        self._admin_service: AdminService | None = None
        # None when the address is not a Collaborative Inbox group, or when the
        # credential cannot read group settings.
        self._member_emails_by_group: dict[str, frozenset[str] | None] = {}

    def has_settings_access(self) -> bool:
        return self._get_settings_service() is not None

    def get_group(self, message: dict[str, Any], mailbox_email: str) -> str | None:
        """The Collaborative Inbox group that delivered this copy of the
        message, when the mailbox belongs to the group. Any sender can set the
        headers, so they alone do not make a copy group mail."""
        if not self._group_emails:
            return None
        group_email = get_delivering_group(message, self._group_emails)
        if group_email is None:
            return None
        member_emails = self._get_member_emails(group_email)
        if member_emails is None or mailbox_email.lower() not in member_emails:
            return None
        return group_email

    def get_groups_of_member(self, mailbox_email: str) -> list[str]:
        return [
            group_email
            for group_email in sorted(self._group_emails)
            if mailbox_email.lower() in (self._get_member_emails(group_email) or ())
        ]

    def get_groups_without_collaborative_inbox(self) -> list[str]:
        return [
            group_email
            for group_email in sorted(self._group_emails)
            if self._get_member_emails(group_email) is None
        ]

    def _get_settings_service(self) -> GroupsSettingsService | None:
        if not self._is_settings_service_built:
            self._settings_service = build_groups_settings_service(
                self._creds, self._primary_admin_email
            )
            self._is_settings_service_built = True
        return self._settings_service

    def _get_member_emails(self, group_email: str) -> frozenset[str] | None:
        if group_email not in self._member_emails_by_group:
            settings_service = self._get_settings_service()
            self._member_emails_by_group[group_email] = (
                frozenset(self._list_member_emails(group_email))
                if settings_service is not None
                and is_collaborative_inbox(settings_service, group_email)
                else None
            )
        return self._member_emails_by_group[group_email]

    def _list_member_emails(self, group_email: str) -> Iterator[str]:
        if self._admin_service is None:
            self._admin_service = get_google_service(
                GoogleService.ADMIN, self._creds, self._primary_admin_email
            )
        return list_group_member_emails(self._admin_service, group_email)
