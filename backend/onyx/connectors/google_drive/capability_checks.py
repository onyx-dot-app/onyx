"""Capability checks for the Google Drive connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
(one page, or the first in-scope item) with the gateway operations its sync
calls.

Two credential kinds need different checks. The form sets the kind of the
picked credential in the ``credential_kind`` config field, so a check for one
kind requires that field:

- A service account acts as each user of the Workspace through domain-wide
  delegation. It lists the users with the Admin SDK, and it reads each shared
  drive as one of its organizers.
- An OAuth token acts as the user who connected Drive (the primary admin)
  and reads only what that user sees.

Scope-dependent checks need the connector config; the credential checks run
without it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from itertools import islice
from typing import Any, NoReturn

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.findings import bounded_count, bounded_options
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckFindingKey,
    CheckOutput,
    CheckRowText,
    CheckStep,
    CountFinding,
    CredentialCapability,
    OptionsFinding,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.google_drive.config import (
    GoogleDriveConnectorConfig,
    has_specific_requests,
)
from onyx.connectors.google_drive.connector import (
    extract_ids_from_urls,
    extract_str_list_from_comma_str,
)
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_SHORTCUT_TYPE,
)
from onyx.connectors.google_drive.doc_conversion import GOOGLE_MIME_TYPES_TO_EXPORT
from onyx.connectors.google_drive.drive_access import (
    OrganizerChoice,
    list_drive_members,
    list_group_member_emails,
    select_drive_organizer,
)
from onyx.connectors.google_drive.models import (
    GDriveMimeType,
    GoogleDirectoryUser,
    GoogleDriveAuth,
    GoogleDriveFileType,
    GoogleSharedDrive,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    ExportSizeThresholdExceeded,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    GOOGLE_SCOPES,
    MISSING_SCOPES_ERROR_STR,
    SCOPE_DOC_URL,
    GoogleCredentialKind,
    google_credential_kind,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = SCOPE_DOC_URL
_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description="The check ran past its time limit.\nRe-run the checks.",
)

_DRIVE_API = "Google Drive API"
_ADMIN_API = "Admin SDK API"
_DOCS_API = "Google Docs API"

_ID_FIELDS = "nextPageToken, files(id)"
_SAMPLE_FIELDS = "nextPageToken, files(id, name, mimeType, size)"
# Files sampled when a probe needs a file to download.
_SAMPLE_FILES = 20
# The download probe reads at most this much of a file.
_MAX_PROBE_BYTES = 5 * 1024 * 1024
# Users impersonated when a check probes listed users one by one.
_MAX_PROBED_USERS = 25
# Users read when a check needs the Workspace user list, as indexing reads it.
_MAX_LISTED_USERS = 5000
_ERROR_DETAIL_CHARS = 300
_SHARED_DRIVE_FIELD = "shared_drive_urls"
# The URL form of a shared drive or folder that the config fields take.
_FOLDER_URL = "https://drive.google.com/drive/folders/{}"

_DISABLED_API_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
_SCOPE_REASONS = frozenset(
    {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
)
_DOWNLOAD_BLOCKED_REASONS = frozenset({"cannotDownloadFile", "cannotExportFile"})
# What Google's token endpoint says when the service account's key is deleted
# or not the account's: the key, not domain-wide delegation, is the problem.
_BAD_KEY_TEXTS = ("Invalid JWT Signature", "invalid_client")

_WORKSPACE_USERS_CHECK_ID = "google_drive_workspace_users"
_SHARED_DRIVES_CHECK_ID = "google_drive_shared_drives"
# check_id to the checks it runs after, in run order. A listed check that does
# not apply (another credential kind, a scope not in use) is left out.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _WORKSPACE_USERS_CHECK_ID: ("google_drive_auth",),
    "google_drive_user_count": (_WORKSPACE_USERS_CHECK_ID,),
    "google_drive_directory_users": ("google_drive_auth",),
    "google_drive_specific_users": (_WORKSPACE_USERS_CHECK_ID,),
    "google_drive_configured_my_drives": (_WORKSPACE_USERS_CHECK_ID,),
    _SHARED_DRIVES_CHECK_ID: ("google_drive_auth",),
    "google_drive_shared_drive_listing": (_SHARED_DRIVES_CHECK_ID,),
    "google_drive_configured_shared_drives": (_SHARED_DRIVES_CHECK_ID,),
    "google_drive_shared_drive_organizer": (_SHARED_DRIVES_CHECK_ID,),
    "google_drive_configured_folders": ("google_drive_auth",),
    "google_drive_content_read": ("google_drive_auth",),
    "google_drive_docs_api": ("google_drive_auth",),
    "google_drive_file_permissions": ("google_drive_auth",),
    "google_drive_folder_permissions": ("google_drive_file_permissions",),
    "google_drive_directory_admin": ("google_drive_auth",),
    "google_drive_groups": ("google_drive_directory_admin",),
    "google_drive_shared_drive_members": (
        _SHARED_DRIVES_CHECK_ID,
        "google_drive_directory_admin",
    ),
}
# Checks that show on another check's row.
_ROW_IDS: dict[str, str] = {
    "google_drive_user_count": _WORKSPACE_USERS_CHECK_ID,
    "google_drive_directory_users": _WORKSPACE_USERS_CHECK_ID,
    "google_drive_shared_drive_listing": _SHARED_DRIVES_CHECK_ID,
}


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _gateway(context: CapabilityCheckContext) -> GoogleDriveSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, GoogleDriveSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _is_service_account(auth: GoogleDriveAuth) -> bool:
    return auth.kind == GoogleCredentialKind.SERVICE_ACCOUNT


def _is_oauth(context: CapabilityCheckContext) -> bool:
    return google_credential_kind(context.credential_json) == GoogleCredentialKind.OAUTH


def _scope_need(context: CapabilityCheckContext) -> str:
    """The row description's line of the scopes to grant, for the credential
    kind. ``_scope_hint`` is the full text for the message."""
    if _is_oauth(context):
        return "Connect Google Drive again and accept every permission."
    return "Give the service account's client ID the scopes in domain-wide delegation."


def _scope_hint(context: CapabilityCheckContext) -> str:
    if _is_oauth(context):
        return "Connect Google Drive again and accept every permission Onyx asks for."
    scopes: str = ", ".join(GOOGLE_SCOPES[DocumentSource.GOOGLE_DRIVE])
    return (
        "In the Google Admin console (Security > API controls > Domain-wide "
        "delegation), give the service account's client ID these scopes: "
        f"{scopes}."
    )


def _detail(error: Exception) -> str:
    return str(error)[:_ERROR_DETAIL_CHARS]


@contextmanager
def _google_errors(
    context: CapabilityCheckContext,
    *,
    api: str,
    denied: str,
    denied_row: _RowText | None = None,
    not_found: str | None = None,
    not_found_row: _RowText | None = None,
) -> Iterator[None]:
    """Maps the gateway's errors onto the validation-exception family.
    ``api`` names the Google API the probe calls; ``denied`` explains a 403.
    Each ``*_row`` is the row text of that outcome."""
    try:
        yield
    except (GoogleDriveRefreshError, GoogleDriveHttpError, PermissionError) as e:
        _raise_google_error(
            context,
            e,
            api=api,
            denied=denied,
            denied_row=denied_row,
            not_found=not_found,
            not_found_row=not_found_row,
        )


def _admin(context: CapabilityCheckContext) -> str:
    return str(
        context.credential_json.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
        or "the primary admin"
    )


def _raise_google_error(
    context: CapabilityCheckContext,
    error: Exception,
    *,
    api: str,
    denied: str,
    denied_row: _RowText | None = None,
    not_found: str | None = None,
    not_found_row: _RowText | None = None,
) -> NoReturn:
    try:
        raise error
    except ConnectorMissingCredentialError as e:
        raise ConnectorValidationError(
            "The credential has no primary admin email. Edit the credential and "
            "set it.",
            summary="Account has no primary admin email",
            description=(
                "The account does not name a Google user to act as.\n"
                "Edit the account and enter a Primary Admin Email."
            ),
        ) from e
    except GoogleDriveRefreshError as e:
        message: str = str(e)
        if MISSING_SCOPES_ERROR_STR in message or "unauthorized_client" in message:
            raise InsufficientPermissionsError(
                f"Google refused the scopes Onyx asks for. {_scope_hint(context)}",
                summary="Google refused the requested scopes",
                description=(
                    "Google does not let the account act with the scopes the "
                    f"connector needs.\n{_scope_need(context)}"
                ),
            ) from e
        if _is_oauth(context):
            raise CredentialExpiredError(
                "Google refused the OAuth credential: it was revoked or it "
                "expired. Connect Google Drive again.",
                summary="Google sign-in was revoked or expired",
                description=(
                    "Google no longer accepts the OAuth grant.\n"
                    "Connect Google Drive again."
                ),
            ) from e
        if any(text in message for text in _BAD_KEY_TEXTS):
            # A deleted or wrong key, not a delegation problem.
            raise CredentialInvalidError(
                f"Google refused the service account's key ({_detail(e)}). Upload "
                "a new JSON key for the service account.",
                summary="Google no longer accepts the account",
                description=(
                    "Google refused to issue a token for this account.\n"
                    "Upload a new JSON key for the service account."
                ),
            ) from e
        raise InsufficientPermissionsError(
            "Google refused to let the service account act as "
            f"{_admin(context)}. Check that the user exists, is not "
            "suspended, and that domain-wide delegation is set up for the "
            f"service account ({_detail(e)}).",
            summary=f"Cannot act as {_admin(context)}",
            description=(
                "Google refused to let the service account act as the primary "
                "admin.\nCheck that the user exists and is active, and that "
                "domain-wide delegation is set up."
            ),
        ) from e
    except GoogleDriveHttpError as e:
        if e.status_code == 401:
            raise CredentialExpiredError(
                "Google rejected the credential (HTTP 401). It was revoked or it "
                "expired.",
                summary="Google rejected the account's token",
                description=(
                    "Google rejected the access token. (HTTP 401)\n"
                    + (
                        "Connect Google Drive again."
                        if _is_oauth(context)
                        else "Upload a new JSON key."
                    )
                ),
            ) from e
        if _DISABLED_API_REASONS.intersection(e.reasons):
            raise ConnectorValidationError(
                f"The {api} is turned off in the Google Cloud project of the "
                "credential. Turn it on in the Google Cloud console (APIs & "
                "Services > Library).",
                summary=f"{api} is turned off",
                description=(
                    f"The {api} is off in the account's Google Cloud project.\n"
                    f"Turn on the {api} in the Google Cloud console (APIs & "
                    "Services > Library)."
                ),
            ) from e
        if _SCOPE_REASONS.intersection(e.reasons):
            raise InsufficientPermissionsError(
                f"The credential is missing a scope Onyx needs. {_scope_hint(context)}",
                summary="Account is missing a required scope",
                description=(
                    "The token lacks a scope this request needs.\n"
                    f"{_scope_need(context)}"
                ),
            ) from e
        if e.rate_limited:
            raise RateLimitedValidationError(
                "Google rate limited the check. Run the checks again in a minute.",
                summary="Rate limited by Google Drive",
                description=(
                    "Google limited the request rate. (HTTP 429)\n"
                    "Wait a minute, then re-run."
                ),
            ) from e
        if e.status_code == 403:
            raise InsufficientPermissionsError(
                f"{denied} (HTTP 403).",
                summary=denied_row.summary if denied_row else None,
                description=denied_row.description if denied_row else None,
            ) from e
        if e.status_code == 404:
            # A 404 is what the check asked for not existing: a clear failure,
            # not an unexpected answer.
            raise ConnectorValidationError(
                f"{not_found or 'Google found nothing at the requested ID'} "
                "(HTTP 404).",
                summary=not_found_row.summary if not_found_row else "Not found",
                description=(
                    not_found_row.description
                    if not_found_row
                    else "Google found nothing at the requested ID. (HTTP 404)"
                ),
            ) from e
        raise UnexpectedValidationError(
            f"Unexpected Google response (HTTP {e.status_code}): {_detail(e)}",
            summary="Unexpected response from Google Drive",
            description=(
                "Google answered with an error the check does not recognize.\n"
                "Re-run the checks. If it repeats, contact support with the "
                "error details."
            ),
        ) from e
    except PermissionError as e:
        # get_google_creds: an invalid key, an unknown credential shape, or an
        # OAuth token that no longer refreshes.
        raise CredentialInvalidError(
            f"Google rejected the credential: {_detail(e)}",
            summary="Google no longer accepts the account",
            description=(
                "Google refused the stored key or token.\n"
                + (
                    "Connect Google Drive again."
                    if _is_oauth(context)
                    else "Upload a new JSON key for the service account."
                )
            ),
        ) from e


def _files(
    listing: Iterator[GoogleDriveFileType | str], count: int
) -> list[GoogleDriveFileType]:
    """The files of a one-page listing; the trailing page token is dropped."""
    return [item for item in islice(listing, count + 1) if not isinstance(item, str)][
        :count
    ]


def _shared_drive_ids(config: GoogleDriveConnectorConfig) -> list[str]:
    return [
        drive_id
        for drive_id in extract_ids_from_urls(
            extract_str_list_from_comma_str(config.shared_drive_urls)
        )
        if drive_id
    ]


def _folder_ids(config: GoogleDriveConnectorConfig) -> list[str]:
    return [
        folder_id
        for folder_id in extract_ids_from_urls(
            extract_str_list_from_comma_str(config.shared_folder_urls)
        )
        if folder_id
    ]


def _shared_drives_in_scope(config: GoogleDriveConnectorConfig) -> bool:
    """The connector ignores the general toggles when a specific request is
    set."""
    if has_specific_requests(config):
        return bool(config.shared_drive_urls)
    return config.include_shared_drives


def _visible_drive_ids(
    ops: GoogleDriveSourceOperations, auth: GoogleDriveAuth
) -> set[str]:
    """The shared drives the connector reads, as it lists them."""
    return set(
        ops.list_drives(
            user_email=auth.primary_admin_email,
            use_domain_admin_access=_is_service_account(auth),
        )
    )


def _candidate_users(
    ops: GoogleDriveSourceOperations,
    auth: GoogleDriveAuth,
    config: GoogleDriveConnectorConfig,
) -> tuple[list[str], bool]:
    """The users the connector acts as, in its order, and whether the list was
    cut at ``_MAX_LISTED_USERS``. An OAuth credential acts as its own user."""
    specific: list[str] = extract_str_list_from_comma_str(config.specific_user_emails)
    if specific:
        return specific, False
    users: list[str] = [auth.primary_admin_email]
    if not _is_service_account(auth):
        return users, False
    listed: list[str] = list(islice(ops.list_user_emails(), _MAX_LISTED_USERS + 1))
    truncated: bool = len(listed) > _MAX_LISTED_USERS
    users.extend(email for email in listed[:_MAX_LISTED_USERS] if email not in users)
    return users, truncated


def _find_viewer(
    ops: GoogleDriveSourceOperations,
    candidates: list[str],
    target_id: str,
) -> tuple[str, GoogleDriveFileType] | None:
    """The first candidate who sees the target, as the connector picks who
    crawls a requested folder."""
    for email in candidates:
        metadata: GoogleDriveFileType | None = ops.probe_target(
            user_email=email, target_id=target_id
        )
        if metadata is not None:
            return email, metadata
    return None


class _GoogleDriveCheck(CapabilityCheck[GoogleDriveConnectorConfig]):
    config_class = GoogleDriveConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_connector_config: bool = False,
        credential_kind: GoogleCredentialKind | None = None,
        discovery: bool = False,
        step: CheckStep | None = None,
        timeout_text: CheckRowText = _TIMEOUT_TEXT,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            row_id=_ROW_IDS.get(check_id),
            depends_on=_DEPENDS_ON.get(check_id, ()),
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            requires_fields=(
                frozenset({"credential_kind"})
                if credential_kind is not None
                else frozenset()
            ),
            remediation=remediation,
            docs_link=_DOCS_LINK,
            discovery=discovery,
            step=step,
            timeout_text=timeout_text,
        )
        self._credential_kind = credential_kind

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        config: GoogleDriveConnectorConfig = form_state.config
        if (
            self._credential_kind is not None
            and config.credential_kind != self._credential_kind
        ):
            return False
        return self.applies_to(config)

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:  # noqa: ARG002
        """False when the check means nothing for this config."""
        return True


class _AuthCheck(_GoogleDriveCheck):
    """Loads the credential and lists one file as the primary admin. A
    service account also opens the admin's My Drive, as each user's crawl
    does first."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_auth",
            display_name="Sign in to Google Drive",
            remediation=(
                "Service account: set up domain-wide delegation with the scopes "
                "in the Onyx docs, and use a Workspace user as the primary admin. "
                "OAuth: connect Google Drive again. Turn on the Google Drive API "
                "in the Google Cloud project of the credential."
            ),
            timeout_text=sign_in_timeout_text("Google Drive"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=(
                "The credential signs in, but Google Drive does not let the "
                "primary admin list files"
            ),
            denied_row=_RowText(
                summary=f"{_admin(context)} cannot list files",
                description=(
                    "The account signs in, but Google Drive refuses to list the "
                    "primary admin's files. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            next(
                ops.list_files(
                    variant=DriveCorpus.USER,
                    user_email=auth.primary_admin_email,
                    fields=_ID_FIELDS,
                    page_size=1,
                    max_num_pages=1,
                ),
                None,
            )
            if _is_service_account(auth):
                ops.get_root_folder_id(user_email=auth.primary_admin_email)
        return CheckOutput(summary=f"Acting as {auth.primary_admin_email}")


class _WorkspaceUsersCheck(_GoogleDriveCheck):
    """A service account lists the Workspace users to crawl each one's
    files."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_WORKSPACE_USERS_CHECK_ID,
            display_name="List Workspace users",
            credential_kind=GoogleCredentialKind.SERVICE_ACCOUNT,
            remediation=(
                "Make the primary admin a Google Workspace admin, give the service "
                "account the admin.directory.user.readonly scope in domain-wide "
                "delegation, and turn on the Admin SDK API. Or list the users to "
                "index in 'Specific user emails'."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return not config.specific_user_emails

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list the Workspace users",
            denied_row=_list_users_denied_row(context),
        ):
            first_admin: str | None = next(
                ops.list_user_emails(query="isAdmin=true"), None
            )
        if first_admin is None:
            raise InconclusiveValidationError(
                "The Workspace directory listed no admin, so Onyx cannot verify "
                "the user listing.",
                summary="Directory listed no admin",
                description=(
                    "The directory search for admins returned nobody.\n"
                    "Re-run the checks. If it repeats, contact support."
                ),
            )
        return CheckOutput(
            summary=f"Users of {first_admin.split('@')[-1]} can be listed"
        )


def _list_users_denied_row(context: CapabilityCheckContext) -> _RowText:
    return _RowText(
        summary=f"{_admin(context)} cannot list users",
        description=(
            "The connector cannot find whose My Drives to index. (HTTP 403)\n"
            f"Make {_admin(context)} a Workspace admin, or list users in Specific "
            "User Emails."
        ),
    )


def _impersonation_failures(
    context: CapabilityCheckContext,
    ops: GoogleDriveSourceOperations,
    emails: list[str],
) -> list[str]:
    """The emails the connector cannot act as, each with the reason."""
    failures: list[str] = []
    for email in emails[:_MAX_PROBED_USERS]:
        try:
            ops.get_root_folder_id(user_email=email)
        except GoogleDriveRefreshError as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                _raise_google_error(context, e, api=_DRIVE_API, denied="")
            failures.append(f"{email} (cannot be impersonated)")
        except GoogleDriveHttpError as e:
            if e.status_code != 401:
                _raise_google_error(
                    context,
                    e,
                    api=_DRIVE_API,
                    denied=f"Google Drive refused to act as {email}",
                    denied_row=_RowText(
                        summary=f"Drive refused to act as {email}",
                        description=(
                            "Google Drive refused a request as this user. "
                            f"(HTTP 403)\nCheck that {email} is an active "
                            "Workspace user with Google Drive turned on."
                        ),
                    ),
                )
            # Indexing skips a user without Drive the same way.
            failures.append(f"{email} (has no Google Drive access)")
    return failures


def _unprobed_users_advisories(user_count: int) -> list[CheckAdvisory]:
    """An advisory for the users past ``_MAX_PROBED_USERS``, which
    ``_impersonation_failures`` does not probe."""
    unprobed: int = user_count - _MAX_PROBED_USERS
    if unprobed <= 0:
        return []
    return [
        CheckAdvisory(
            message=(
                f"Onyx probed only the first {_MAX_PROBED_USERS} users. It did "
                f"not verify that it can act as the other {unprobed} users."
            )
        )
    ]


def _impersonation_error(failures: list[str], what: str) -> ConnectorValidationError:
    return ConnectorValidationError(
        f"Onyx cannot act as these users, so it skips their files: "
        f"{', '.join(failures)}.",
        summary=f"Cannot act as {len(failures)} {what}",
        description=(
            f"The service account cannot act as these users: {', '.join(failures)}."
        ),
    )


class _SpecificUsersCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_specific_users",
            display_name="Act as selected users",
            required=False,
            requires_connector_config=True,
            credential_kind=GoogleCredentialKind.SERVICE_ACCOUNT,
            remediation=(
                "Check the emails in 'Specific user emails': each must be the "
                "primary email of an active Workspace user with Google Drive."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return bool(config.specific_user_emails)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        emails: list[str] = extract_str_list_from_comma_str(
            self.config(context).specific_user_emails
        )
        failures: list[str] = _impersonation_failures(
            context, _gateway(context), emails
        )
        if failures:
            raise _impersonation_error(failures, "selected users")
        advisories: list[CheckAdvisory] = _unprobed_users_advisories(len(emails))
        return CheckOutput(
            summary=(
                f"First {_MAX_PROBED_USERS} of {len(emails)} selected users work"
                if advisories
                else f"Acting as all {len(emails)} selected users"
            ),
            advisories=advisories,
        )


class _OAuthIgnoredSettingsCheck(_GoogleDriveCheck):
    """An OAuth credential reads as its own user only; the per-user settings
    do nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_oauth_user_settings",
            display_name="Check per-user settings",
            required=False,
            requires_connector_config=True,
            credential_kind=GoogleCredentialKind.OAUTH,
            remediation=(
                "To index other users' My Drives, pick a service-account "
                "account. An OAuth account reads only what its own user sees."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return bool(config.my_drive_emails or config.specific_user_emails)

    def run(self, context: CapabilityCheckContext) -> None:
        config: GoogleDriveConnectorConfig = self.config(context)
        ignored: list[str] = [
            name
            for name, value in (
                ("My Drive emails", config.my_drive_emails),
                ("Specific user emails", config.specific_user_emails),
            )
            if value
        ]
        raise ConnectorValidationError(
            f"An OAuth credential indexes only what its own user sees, so Onyx "
            f"ignores {' and '.join(ignored)}.",
            summary=f"{' and '.join(ignored)} ignored with OAuth",
            description=(
                "An OAuth account reads only what its own user sees.\nPick a "
                "service-account account to index other users' My Drives."
            ),
        )


class _SharedDrivesCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_SHARED_DRIVES_CHECK_ID,
            display_name="List shared drives",
            requires_connector_config=True,
            remediation=(
                "Service account: make the primary admin a Workspace admin who "
                "can manage shared drives. OAuth: the connected user must be a "
                "member of the shared drives to index."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return _shared_drives_in_scope(config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GoogleDriveConnectorConfig = self.config(context)
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The primary admin cannot list the shared drives",
            denied_row=_list_drives_denied_row(context),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            first_drive: str | None = next(
                ops.list_drives(
                    user_email=auth.primary_admin_email,
                    use_domain_admin_access=_is_service_account(auth),
                ),
                None,
            )
        if first_drive is not None or config.shared_drive_urls:
            return CheckOutput(summary="Shared drives visible")
        # Not FAILED: the domain can have no shared drive yet.
        return CheckOutput(
            summary="No shared drives visible",
            advisories=[
                CheckAdvisory(
                    message=(
                        "The credential sees no shared drive, so Onyx did not "
                        "verify that it can read shared drives. Shared drives "
                        "index nothing until the credential sees one."
                    )
                )
            ],
        )


def _list_drives_denied_row(context: CapabilityCheckContext) -> _RowText:
    return _RowText(
        summary=f"{_admin(context)} cannot list shared drives",
        description=(
            "The primary admin cannot list shared drives. (HTTP 403)\n"
            f"Make {_admin(context)} a Workspace admin who can manage shared drives."
        ),
    )


def _not_found_output(
    found: int, missing: list[str], *, noun: str, description: str
) -> CheckOutput:
    """A Find that found some selected items: INCOMPLETE, and the checks after
    it run on the items it found."""
    return CheckOutput(
        summary=f"{len(missing)} of {found + len(missing)} {noun} not found",
        description=description,
        partial=True,
    )


@contextmanager
def _admin_sdk_errors(context: CapabilityCheckContext) -> Iterator[None]:
    """For an Admin SDK call inside a Drive probe: its errors name the Admin
    SDK, not the Drive API."""
    with _google_errors(
        context,
        api=_ADMIN_API,
        denied="The primary admin cannot list the Workspace users",
        denied_row=_list_users_denied_row(context),
    ):
        yield


class _ConfiguredSharedDrivesCheck(_GoogleDriveCheck):
    """A configured id that is not a shared drive is crawled as a folder; it
    must be visible to some user the connector acts as."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_shared_drives",
            display_name="Find selected drives",
            requires_connector_config=True,
            remediation=(
                "Use the URL of each shared drive (https://drive.google.com/drive/"
                "folders/<id>). Service account: an organizer of the drive must be "
                "a user Onyx indexes. OAuth: the connected user must be a member."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return bool(config.shared_drive_urls)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GoogleDriveConnectorConfig = self.config(context)
        ops: GoogleDriveSourceOperations = _gateway(context)
        requested: list[str] = _shared_drive_ids(config)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot read the configured shared drives",
            denied_row=_RowText(
                summary="Cannot read the selected shared drives",
                description=(
                    "Google refused a request while looking up the selected "
                    "shared drives. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            visible: set[str] = _visible_drive_ids(ops, auth)
            missing: list[str] = [
                drive_id for drive_id in requested if drive_id not in visible
            ]
            if not missing:
                return CheckOutput(
                    summary=f"All {len(requested)} selected drives found"
                )
            with _admin_sdk_errors(context):
                candidates, truncated = _candidate_users(ops, auth, config)
            unreachable: list[str] = []
            not_folders: list[str] = []
            for drive_id in missing:
                found: tuple[str, GoogleDriveFileType] | None = _find_viewer(
                    ops, candidates, drive_id
                )
                if found is None:
                    unreachable.append(drive_id)
                elif found[1].get("mimeType") != DRIVE_FOLDER_TYPE:
                    not_folders.append(drive_id)
        if not_folders:
            # The crawl lists the children of the id, so a file indexes nothing.
            raise ConnectorValidationError(
                "These IDs are files, not shared drives or folders, so Onyx "
                f"indexes nothing from them: {', '.join(not_folders)}.",
                summary=f"{len(not_folders)} selected IDs are files, not drives",
                description=(
                    f"These IDs point to files: {', '.join(not_folders)}.\n"
                    "Use the URL of each shared drive in Shared Drive URLs."
                ),
            )
        if not unreachable:
            return CheckOutput(summary=f"All {len(requested)} selected drives found")
        if truncated:
            raise InconclusiveValidationError(
                f"No shared drive with the IDs {', '.join(unreachable)} is "
                f"visible to the first {_MAX_LISTED_USERS} users, so Onyx cannot "
                "verify them.",
                summary=f"Drives not seen by first {_MAX_LISTED_USERS:,} users",
                description=(
                    f"None of the first {_MAX_LISTED_USERS:,} users can see these "
                    "shared drives, and the other users were not tested: "
                    f"{', '.join(unreachable)}."
                ),
            )
        description: str = (
            f"No indexed user can see these IDs: {', '.join(unreachable)}.\n"
            "Make an indexed Workspace user an organizer of each drive, and "
            "check each URL."
        )
        if len(unreachable) < len(requested):
            return _not_found_output(
                len(requested) - len(unreachable),
                unreachable,
                noun="selected drives",
                description=description,
            )
        raise ConnectorValidationError(
            f"Nothing with the IDs {', '.join(unreachable)} is visible to the "
            "credential. Onyx cannot index them, and it does not prune the "
            "connector while they stay out of reach.",
            summary="No selected drive found",
            description=description,
        )


class _ConfiguredFoldersCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_folders",
            display_name="Find selected folders",
            requires_connector_config=True,
            remediation=(
                "Use the URL of each folder (https://drive.google.com/drive/"
                "folders/<id>). Put shared drive URLs in 'Shared drive URLs'. "
                "Share each folder with a user Onyx indexes."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return bool(config.shared_folder_urls)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GoogleDriveConnectorConfig = self.config(context)
        ops: GoogleDriveSourceOperations = _gateway(context)
        folder_ids: list[str] = _folder_ids(config)
        unseen: list[str] = []
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot read the configured folders",
            denied_row=_RowText(
                summary="Cannot read the selected folders",
                description=(
                    "Google refused a request while reading the selected "
                    "folders. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            visible_drives: set[str] = _visible_drive_ids(ops, auth)
            requested_drives: set[str] = set(_shared_drive_ids(config))
            with _admin_sdk_errors(context):
                candidates, truncated = _candidate_users(ops, auth, config)
            listed: bool = False
            for folder_id in folder_ids:
                if folder_id in visible_drives:
                    # The connector drops a drive id from the folders.
                    if folder_id not in requested_drives:
                        raise ConnectorValidationError(
                            f"Onyx cannot index the folder {folder_id}: it is a "
                            "shared drive; put its URL in 'Shared drive URLs'.",
                            summary="A selected folder is a shared drive",
                            description=(
                                "The connector drops shared drive IDs from Folder "
                                f"URLs: {folder_id}.\nPut its URL in Shared Drive "
                                "URLs."
                            ),
                        )
                    continue
                found: tuple[str, GoogleDriveFileType] | None = _find_viewer(
                    ops, candidates, folder_id
                )
                if found is None:
                    unseen.append(folder_id)
                    continue
                viewer, metadata = found
                if metadata.get("mimeType") != DRIVE_FOLDER_TYPE:
                    raise ConnectorValidationError(
                        f"Onyx cannot index the folder {folder_id}: it is a "
                        "file, not a folder.",
                        summary="A selected folder URL is a file",
                        description=(
                            "This Folder URL points to a file, not a folder: "
                            f"{folder_id}.\nIn Folder URLs, use the URL of a "
                            "folder."
                        ),
                    )
                if not listed:
                    # The crawl lists each folder's children as its viewer.
                    next(
                        ops.list_files(
                            variant=DriveCorpus.ALL_DRIVES,
                            user_email=viewer,
                            query=f"'{folder_id}' in parents and trashed = false",
                            fields=_ID_FIELDS,
                            page_size=1,
                            max_num_pages=1,
                        ),
                        None,
                    )
                    listed = True
        advisories: list[CheckAdvisory] = [
            CheckAdvisory(
                message=(
                    "Every selected folder is visible. Only the first folder's "
                    "contents were listed."
                )
            )
        ]
        if not unseen:
            return CheckOutput(
                summary=f"All {len(folder_ids)} selected folders found",
                advisories=advisories if len(folder_ids) > 1 else [],
            )
        if truncated:
            raise InconclusiveValidationError(
                f"{', '.join(unseen)} are not visible to the first "
                f"{_MAX_LISTED_USERS} users, so Onyx cannot verify them.",
                summary=f"Folders not seen by first {_MAX_LISTED_USERS:,} users",
                description=(
                    f"None of the first {_MAX_LISTED_USERS:,} users can open these "
                    f"folders, and the other users were not tested: {', '.join(unseen)}."
                ),
            )
        description: str = (
            f"No indexed user can open these folders: {', '.join(unseen)}.\n"
            "Share each folder with a Workspace user who is indexed, and check "
            "each URL."
        )
        if len(unseen) < len(folder_ids):
            return _not_found_output(
                len(folder_ids) - len(unseen),
                unseen,
                noun="selected folders",
                description=description,
            )
        raise ConnectorValidationError(
            f"Onyx cannot index these folders: {', '.join(unseen)} are not "
            "visible to the credential.",
            summary="No selected folder found",
            description=description,
        )


class _ConfiguredMyDrivesCheck(_GoogleDriveCheck):
    """A My Drive email must be the primary email of a listed user: indexing
    skips any other email (an alias, a typo) without an error."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_my_drives",
            display_name="Find My Drive users",
            requires_connector_config=True,
            credential_kind=GoogleCredentialKind.SERVICE_ACCOUNT,
            remediation=(
                "Use each user's primary Workspace email, not an alias. With "
                "'Specific user emails' set, each My Drive email must also be in "
                "that list."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return bool(config.my_drive_emails)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GoogleDriveConnectorConfig = self.config(context)
        ops: GoogleDriveSourceOperations = _gateway(context)
        requested: list[str] = extract_str_list_from_comma_str(config.my_drive_emails)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list users",
            denied_row=_list_users_denied_row(context),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            users, truncated = _candidate_users(ops, auth, config)
        known: set[str] = {email.lower() for email in users}
        found: list[str] = [email for email in requested if email.lower() in known]
        missing: list[str] = [
            email for email in requested if email.lower() not in known
        ]
        if missing and truncated:
            raise InconclusiveValidationError(
                f"{', '.join(missing)} are not among the first {_MAX_LISTED_USERS} "
                "users, so Onyx cannot verify them.",
                summary=f"Users not among the first {_MAX_LISTED_USERS:,} listed",
                description=(
                    f"These emails are not among the first {_MAX_LISTED_USERS:,} "
                    f"users, and the other users were not read: {', '.join(missing)}."
                ),
            )
        missing_description: str = (
            f"These emails are not primary emails of indexed users: "
            f"{', '.join(missing)}.\nIn My Drive Emails, use primary Workspace "
            "emails, not aliases."
        )
        if missing and not found:
            raise ConnectorValidationError(
                f"Onyx skips these My Drives: {', '.join(missing)} are not "
                "primary emails of the users it indexes.",
                summary="No My Drive user found",
                description=missing_description,
            )
        failures: list[str] = _impersonation_failures(context, ops, found)
        if failures:
            raise _impersonation_error(failures, "My Drive users")
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=f"Google Drive does not let {found[0]} list files",
            denied_row=_RowText(
                summary=f"{found[0]} cannot list their files",
                description=(
                    "Google Drive refuses to list this user's files. (HTTP 403)\n"
                    f"Check that {found[0]} has Google Drive turned on."
                ),
            ),
        ):
            next(
                ops.list_files(
                    variant=DriveCorpus.USER,
                    user_email=found[0],
                    query="'me' in owners and trashed = false",
                    fields=_ID_FIELDS,
                    page_size=1,
                    max_num_pages=1,
                ),
                None,
            )
        if missing:
            return _not_found_output(
                len(found),
                missing,
                noun="My Drive users",
                description=missing_description,
            )
        advisories: list[CheckAdvisory] = _unprobed_users_advisories(len(found))
        return CheckOutput(
            summary=(
                f"All {len(found)} found; first {_MAX_PROBED_USERS} tested"
                if advisories
                else f"All {len(found)} My Drive users found"
            ),
            advisories=advisories,
        )


class _SharedDriveOrganizerCheck(_GoogleDriveCheck):
    """A service account reads each shared drive as an organizer, the one role
    that sees folders with limited access. Probes the first drive in scope."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_shared_drive_organizer",
            display_name="Find drive organizers",
            required=False,
            requires_connector_config=True,
            credential_kind=GoogleCredentialKind.SERVICE_ACCOUNT,
            remediation=(
                "Make a Workspace user a Manager of each shared drive, and keep "
                "that user in the users Onyx indexes. Without one, Onyx can miss "
                "folders with limited access."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return _shared_drives_in_scope(config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GoogleDriveConnectorConfig = self.config(context)
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=(
                "Onyx cannot read the members of a shared drive, so it reads "
                "shared drives as the primary admin and can miss folders with "
                "limited access"
            ),
            denied_row=_RowText(
                summary="Cannot read shared drive members",
                description=(
                    "The primary admin cannot read who belongs to a shared "
                    "drive. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            visible: set[str] = _visible_drive_ids(ops, auth)
            configured: list[str] = [
                drive_id
                for drive_id in _shared_drive_ids(config)
                if drive_id in visible
            ]
            drive_id: str | None = next(iter(configured or sorted(visible)), None)
            if drive_id is None:
                raise NothingToCheckError(
                    "The primary admin sees no shared drive, so there is no "
                    "organizer to find.",
                    summary="No shared drives to test",
                    description="The primary admin sees no shared drive.",
                )
            choice: OrganizerChoice = select_drive_organizer(
                drive_id=drive_id,
                members=list_drive_members(ops, drive_id),
                google_domain=auth.primary_admin_email.split("@")[-1],
                expand_group=lambda group: list_group_member_emails(ops, group),
                can_list_drive=lambda email: ops.can_list_drive(
                    user_email=email, drive_id=drive_id
                ),
            )
            if choice.email is None:
                raise ConnectorValidationError(
                    f"No member of shared drive {drive_id} is a Workspace user "
                    "Onyx can act as, so Onyx reads it as the primary admin, if "
                    "the admin can see it.",
                    summary=f"Drive {drive_id} has no member to act as",
                    description=(
                        "No member of the shared drive is a Workspace user the "
                        "service account can act as."
                    ),
                )
            if not choice.complete:
                role: str = choice.role.value if choice.role else "member"
                raise ConnectorValidationError(
                    f"Shared drive {drive_id} has no organizer Onyx can act as, so "
                    f"Onyx reads it as {choice.email} ({role}) and can miss folders "
                    "with limited access.",
                    summary=f"Drive {drive_id} has no usable Manager",
                    description=(
                        "No Manager of the shared drive can be acted as.\nMake an "
                        "indexed Workspace user a Manager of each shared drive."
                    ),
                )
            next(
                ops.list_files(
                    variant=DriveCorpus.DRIVE,
                    user_email=choice.email,
                    drive_id=drive_id,
                    fields=_ID_FIELDS,
                    page_size=1,
                    max_num_pages=1,
                ),
                None,
            )
        return CheckOutput(
            summary=f"Organizer {choice.email} found",
            advisories=[
                CheckAdvisory(
                    message=(
                        "One shared drive has a Manager the service account can "
                        "act as. The other drives were not tested."
                    )
                )
            ],
        )


class _SharedDriveListingCheck(_GoogleDriveCheck):
    """Lists every shared drive the connector would read, as options for the
    shared drive field. Separate from ``google_drive_shared_drives``, which
    reads one drive to validate. Applies only when the config indexes shared
    drives."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_shared_drive_listing",
            display_name="List shared drives",
            discovery=True,
            step=CheckStep(
                step_of=_SHARED_DRIVES_CHECK_ID,
                running_summary="Drives visible, counting…",
                unfinished_caveat="Could not count every shared drive.",
            ),
            requires_connector_config=True,
            remediation=(
                "Service account: make the primary admin a Workspace admin who "
                "can manage shared drives. OAuth: the connected user must be a "
                "member of the shared drives to index."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return _shared_drives_in_scope(config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The primary admin cannot list the shared drives",
            denied_row=_list_drives_denied_row(context),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            finding: OptionsFinding = bounded_options(
                ops.list_named_drives(
                    user_email=auth.primary_admin_email,
                    use_domain_admin_access=_is_service_account(auth),
                ),
                key=CheckFindingKey.SHARED_DRIVES,
                field_name=_SHARED_DRIVE_FIELD,
                value=_shared_drive_url,
                label=lambda drive: drive.name or drive.id,
            )
        count: str = f"{len(finding.options):,}{'+' if finding.truncated else ''}"
        return CheckOutput(summary=f"{count} shared drives found", findings=[finding])


def _shared_drive_url(drive: GoogleSharedDrive) -> str:
    return _FOLDER_URL.format(drive.id)


class _UserCountCheck(_GoogleDriveCheck):
    """Counts the Workspace users a service account lists: the users whose My
    Drives indexing reads. It does not probe each user, so a user without
    Google Drive still counts. Applies only when the config indexes every
    user's My Drive: not with specific requests or specific user emails."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_user_count",
            display_name="List Workspace users",
            discovery=True,
            step=CheckStep(
                step_of=_WORKSPACE_USERS_CHECK_ID,
                running_summary="Users listed, counting…",
                unfinished_caveat="Could not count every user.",
            ),
            credential_kind=GoogleCredentialKind.SERVICE_ACCOUNT,
            remediation=(
                "Make the primary admin a Google Workspace admin, give the service "
                "account the admin.directory.user.readonly scope in domain-wide "
                "delegation, and turn on the Admin SDK API."
            ),
        )

    def applies_to(self, config: GoogleDriveConnectorConfig) -> bool:
        return (
            config.include_my_drives
            and not has_specific_requests(config)
            and not config.specific_user_emails
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list the Workspace users",
            denied_row=_list_users_denied_row(context),
        ):
            ops.authenticate()
            finding: CountFinding = bounded_count(
                ops.list_user_emails(),
                key=CheckFindingKey.VISIBLE_ORGANIZATION_USERS,
                cap=MAX_FINDING_OPTIONS,
            )
        count: str = f"{finding.count:,}{'+' if finding.at_least else ''}"
        return CheckOutput(summary=f"{count} Workspace users found", findings=[finding])


def _sample_files(
    ops: GoogleDriveSourceOperations, user_email: str, query: str
) -> list[GoogleDriveFileType]:
    return _files(
        ops.list_files(
            variant=DriveCorpus.ALL_DRIVES,
            user_email=user_email,
            query=query,
            fields=_SAMPLE_FIELDS,
            page_size=_SAMPLE_FILES,
            max_num_pages=1,
        ),
        _SAMPLE_FILES,
    )


def _size(file: GoogleDriveFileType) -> int | None:
    try:
        return int(file["size"])
    except (KeyError, TypeError, ValueError):
        return None


class _ContentReadCheck(_GoogleDriveCheck):
    """Downloads one small uploaded file and exports one Google Doc, Sheet or
    Slides file among the files the primary admin sees. Passes when the sample
    has none."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_content_read",
            display_name="Sample file content",
            required=False,
            remediation=(
                "Give the service account the drive.readonly scope (OAuth: "
                "connect again and accept every permission). A file owner can "
                "also block downloads for viewers; Onyx skips those files."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list files",
            denied_row=_RowText(
                summary=f"Cannot list files as {_admin(context)}",
                description=(
                    "Google Drive refuses to list the primary admin's files. "
                    f"(HTTP 403)\n{_scope_need(context)}"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            files: list[GoogleDriveFileType] = _sample_files(
                ops,
                auth.primary_admin_email,
                f"mimeType != '{DRIVE_FOLDER_TYPE}' and "
                f"mimeType != '{DRIVE_SHORTCUT_TYPE}' and trashed = false",
            )
        native: GoogleDriveFileType | None = next(
            (
                file
                for file in files
                if file.get("mimeType") in GOOGLE_MIME_TYPES_TO_EXPORT
            ),
            None,
        )
        uploaded: list[tuple[int, GoogleDriveFileType]] = [
            (size, file)
            for file in files
            if file.get("mimeType") not in GOOGLE_MIME_TYPES_TO_EXPORT
            and (size := _size(file)) is not None
            and size <= _MAX_PROBE_BYTES
        ]
        smallest: GoogleDriveFileType | None = (
            min(uploaded, key=lambda item: item[0])[1] if uploaded else None
        )
        read: list[GoogleDriveFileType] = [
            file for file in (native, smallest) if file is not None
        ]
        if not read:
            raise InconclusiveValidationError(
                f"The primary admin's first {_SAMPLE_FILES} files hold no Google "
                "file and no small upload, so Onyx did not verify downloads.",
                summary="No files found to test",
                description=(
                    f"The primary admin's first {_SAMPLE_FILES} files hold no "
                    "Google file and no upload of 5 MB or less."
                ),
            )
        for file in read:
            self._read(context, ops, auth, file)
        return CheckOutput(
            summary=f"Read {len(read)} sample files",
            advisories=[
                CheckAdvisory(
                    message="The sampled files downloaded. Other files were not tested."
                )
            ],
        )

    def _read(
        self,
        context: CapabilityCheckContext,
        ops: GoogleDriveSourceOperations,
        auth: GoogleDriveAuth,
        file: GoogleDriveFileType,
    ) -> None:
        name: str = file.get("name") or file["id"]
        mime_type: str | None = file.get("mimeType")
        try:
            if mime_type in GOOGLE_MIME_TYPES_TO_EXPORT:
                ops.export_file(
                    user_email=auth.primary_admin_email,
                    file_id=file["id"],
                    mime_type=GOOGLE_MIME_TYPES_TO_EXPORT[mime_type],
                    size_threshold=_MAX_PROBE_BYTES,
                )
            else:
                ops.download_file(
                    user_email=auth.primary_admin_email,
                    file_id=file["id"],
                    size_threshold=_MAX_PROBE_BYTES,
                )
        except ExportSizeThresholdExceeded:
            # The download started, so the credential can read the file.
            return
        except GoogleDriveHttpError as e:
            if _DOWNLOAD_BLOCKED_REASONS.intersection(e.reasons):
                raise InconclusiveValidationError(
                    f"The owner of '{name}' blocked downloads for viewers, so "
                    "Onyx skips files like it.",
                    summary="Sampled file blocks downloads",
                    description=(
                        f"The owner of {name} blocked downloads for viewers.\n"
                        "Re-run the checks later, or ask the owner to allow "
                        "downloads for viewers."
                    ),
                ) from e
            _raise_google_error(
                context,
                e,
                api=_DRIVE_API,
                denied=f"The credential can see '{name}' but cannot download it",
                denied_row=_RowText(
                    summary=f"Cannot download {name}",
                    description=(
                        "The account can see the file, but Google refuses the "
                        "download. (HTTP 403)"
                    ),
                ),
            )
        except GoogleDriveRefreshError as e:
            _raise_google_error(context, e, api=_DRIVE_API, denied="")


class _DocsApiCheck(_GoogleDriveCheck):
    """Reads one Google Doc through the Docs API, which gives indexed Docs
    their heading links. Passes when the primary admin sees no Google Doc."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_docs_api",
            display_name="Use Google Docs API",
            required=False,
            remediation=(
                "Turn on the Google Docs API in the Google Cloud project of the "
                "credential. Without it, Google Docs index without links to their "
                "headings."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list Google Docs",
            denied_row=_RowText(
                summary="Cannot list Google Docs",
                description=(
                    "Google Drive refuses to list the primary admin's Google "
                    "Docs. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            docs: list[GoogleDriveFileType] = _sample_files(
                ops,
                auth.primary_admin_email,
                f"mimeType = '{GDriveMimeType.DOC.value}' and trashed = false",
            )
        if not docs:
            raise InconclusiveValidationError(
                "The primary admin sees no Google Doc, so Onyx did not verify the "
                "Docs API.",
                summary="No Google Docs found to test",
                description=(
                    f"The primary admin's first {_SAMPLE_FILES} Google Docs query "
                    "returned none."
                ),
            )
        with _google_errors(
            context,
            api=_DOCS_API,
            denied="The credential cannot read Google Docs through the Docs API",
            denied_row=_RowText(
                summary="Docs API refused to read a Doc",
                description=(
                    "Docs would index without links to their headings. (HTTP 403)\n"
                    f"{_scope_need(context)}"
                ),
            ),
        ):
            ops.fetch_google_doc(
                user_email=auth.primary_admin_email,
                doc_id=docs[0]["id"],
                max_response_bytes=_MAX_PROBE_BYTES,
            )
        return CheckOutput(summary="Google Docs API is on")


def build_google_drive_indexing_checks() -> list[CapabilityCheck]:
    return [
        _AuthCheck(),
        _WorkspaceUsersCheck(),
        _SpecificUsersCheck(),
        _OAuthIgnoredSettingsCheck(),
        _SharedDrivesCheck(),
        _ConfiguredSharedDrivesCheck(),
        _ConfiguredFoldersCheck(),
        _ConfiguredMyDrivesCheck(),
        _SharedDriveOrganizerCheck(),
        _ContentReadCheck(),
        _DocsApiCheck(),
        _SharedDriveListingCheck(),
        _UserCountCheck(),
    ]


# Permission sync. The EE registry registers these checks. Doc sync re-lists
# the files with their permissions and reads the permissions Drive gives only
# by id (shared drive files, folders). Group sync reads the Workspace
# directory (users, groups and their members), the members of each shared
# drive, and the permissions of each folder. Both kinds of credential need a
# primary admin who is a Workspace admin.

_PERMISSION_SAMPLE_FIELDS = (
    "nextPageToken, files(id, name, permissionIds, "
    "permissions(id, emailAddress, type, domain))"
)
_PERMISSION_FIELDS = "permissions(id, emailAddress, type),nextPageToken"
# Permission reads the file check makes before it gives up.
_MAX_PERMISSION_READS = 3
_DIRECTORY_HINT = (
    "Make the primary admin a Google Workspace admin. Service account: give it "
    "the admin.directory.user.readonly and admin.directory.group.readonly "
    "scopes in domain-wide delegation. Turn on the Admin SDK API."
)


def _is_item_denial(error: GoogleDriveHttpError) -> bool:
    """A 403 or 404 on one file or folder, not a disabled API or a missing
    scope."""
    return (
        error.status_code in (403, 404)
        and error.access_denied
        and not _DISABLED_API_REASONS.intersection(error.reasons)
        and not _SCOPE_REASONS.intersection(error.reasons)
    )


def _read_permissions(
    context: CapabilityCheckContext,
    ops: GoogleDriveSourceOperations,
    user_email: str,
    item: GoogleDriveFileType,
) -> bool:
    """Reads the permissions of a file or folder that lists them only by id,
    as the sync does. False when Google denies them for this item or returns
    none."""
    try:
        permissions: list[dict[str, Any]] = list(
            ops.list_file_permissions(
                user_email=user_email, file_id=item["id"], fields=_PERMISSION_FIELDS
            )
        )
    except GoogleDriveHttpError as e:
        if _is_item_denial(e):
            return False
        _raise_google_error(
            context, e, api=_DRIVE_API, denied="The credential cannot read permissions"
        )
    except GoogleDriveRefreshError as e:
        _raise_google_error(context, e, api=_DRIVE_API, denied="")
    return bool(permissions)


class _FilePermissionsCheck(_GoogleDriveCheck):
    """Lists files with their permissions as the primary admin, and reads the
    permissions of files that have them only by id. Google denies the
    permissions of some files (for example files of another organization); the
    sync gives those files to the user who found them, so one denial is not a
    failure."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="google_drive_file_permissions",
            display_name="Read file permissions",
            remediation=(
                "Give the service account the drive.readonly and "
                "drive.metadata.readonly scopes (OAuth: connect again and accept "
                "every permission)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list files with their permissions",
            denied_row=_RowText(
                summary="Cannot list files with permissions",
                description=(
                    "Google Drive refuses to list files with who can open them. "
                    "(HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            files: list[GoogleDriveFileType] = _files(
                ops.list_files(
                    variant=DriveCorpus.ALL_DRIVES,
                    user_email=auth.primary_admin_email,
                    query="trashed = false",
                    fields=_PERMISSION_SAMPLE_FIELDS,
                    page_size=_SAMPLE_FILES,
                    max_num_pages=1,
                ),
                _SAMPLE_FILES,
            )
        if not files:
            raise NothingToCheckError(
                "The primary admin sees no file, so there are no permissions to read.",
                summary="No files in scope",
                description="The primary admin sees no file.",
            )
        by_id_only: list[GoogleDriveFileType] = [
            file
            for file in files
            if file.get("permissionIds") and not file.get("permissions")
        ][:_MAX_PERMISSION_READS]
        readable: int = sum(1 for file in files if file.get("permissions")) + sum(
            1
            for file in by_id_only
            if _read_permissions(context, ops, auth.primary_admin_email, file)
        )
        if readable:
            return CheckOutput(
                summary=f"Read permissions on {readable} files",
                advisories=[
                    CheckAdvisory(
                        message=(
                            "Permissions were readable on the sampled files. "
                            "Other files were not tested."
                        )
                    )
                ],
            )
        if by_id_only:
            raise InconclusiveValidationError(
                "Google Drive denied the permissions of every sampled file, so "
                "Onyx cannot verify the permission sync. The sync gives such "
                "files only to the user who found them.",
                summary="No sampled file's permissions readable",
                description=(
                    "Google denied the permissions of every sampled file.\n"
                    f"{_scope_need(context)}"
                ),
            )
        raise InsufficientPermissionsError(
            "Google Drive listed files without their permissions, so Onyx "
            "cannot tell who can open them. Give the credential the "
            "drive.metadata.readonly scope.",
            summary="Files listed without their permissions",
            description=(
                f"Google returned files without who can open them.\n{_scope_need(context)}"
            ),
        )


class _DirectoryAdminCheck(_GoogleDriveCheck):
    """Reads the primary admin's directory entry, as group sync does first."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_directory_admin",
            display_name="Use Workspace directory",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        admin: str | None = context.credential_json.get(
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY
        )
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied=(
                f"Primary admin {admin or ''} is not authorized on the Google "
                "Workspace directory API. Reconnect the connector with an "
                "account that has admin directory access"
            ),
            denied_row=_RowText(
                summary=f"{_admin(context)} cannot read the directory",
                description=(
                    "The primary admin cannot read the Workspace directory. (HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            admin_user: GoogleDirectoryUser = ops.get_admin_user()
        return CheckOutput(
            summary=(
                f"{auth.primary_admin_email} is a Workspace admin"
                if admin_user.is_admin or admin_user.is_delegated_admin
                else f"{auth.primary_admin_email} can read the directory"
            )
        )


class _DirectoryUsersCheck(_GoogleDriveCheck):
    """Group sync puts every listed user in the group of the Workspace domain,
    which "anyone at the domain" shares grant."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_directory_users",
            display_name="List Workspace users",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list the Workspace users",
            denied_row=_list_users_denied_row(context),
        ):
            ops.authenticate()
            first_user: str | None = next(ops.list_user_emails(), None)
        if first_user is None:
            raise InconclusiveValidationError(
                "The Workspace directory listed no user, so Onyx cannot verify "
                "the user listing.",
                summary="Directory listed no user",
                description=(
                    "The user listing returned nobody.\n"
                    "Re-run the checks. If it repeats, contact support."
                ),
            )
        return CheckOutput(
            summary=f"Users of {first_user.split('@')[-1]} can be listed"
        )


class _GroupsCheck(_GoogleDriveCheck):
    """Lists the groups and reads the members of the first. Passes when the
    domain has no group."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_groups",
            display_name="Read group members",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot read the Workspace groups",
            denied_row=_RowText(
                summary=f"{_admin(context)} cannot read groups",
                description=(
                    "Sharing through groups would not sync. (HTTP 403)\n"
                    f"Make {_admin(context)} a Workspace admin."
                ),
            ),
        ):
            ops.authenticate()
            first_group: str | None = next(ops.list_groups(), None)
            if first_group is None:
                return CheckOutput(
                    summary="No groups in the Workspace",
                    advisories=[
                        CheckAdvisory(
                            message=(
                                "The group list is readable but empty, so reading "
                                "group members was not tested."
                            )
                        )
                    ],
                )
            next(ops.list_group_members(group_email=first_group), None)
        return CheckOutput(
            summary=f"Members of {first_group} readable",
            advisories=[
                CheckAdvisory(
                    message=(
                        "Groups and one group's members are readable. Other "
                        "groups were not tested."
                    )
                )
            ],
        )


class _DriveMembershipCheck(_GoogleDriveCheck):
    """Reads the members of the first shared drive, as group sync reads every
    drive. A primary admin who is not a Workspace admin reads only the drives
    it is a member of."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_shared_drive_members",
            display_name="Read drive members",
            required=False,
            remediation=(
                "Make the primary admin a Workspace admin who can manage shared "
                "drives. Without it, users get access to shared drive files only "
                "through the files' own permissions."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _admin_sdk_errors(context):
            auth: GoogleDriveAuth = ops.authenticate()
            admin_user: GoogleDirectoryUser = ops.get_admin_user()
        is_admin: bool = admin_user.is_admin or admin_user.is_delegated_admin
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The primary admin cannot read the members of shared drives",
            denied_row=_RowText(
                summary="Cannot read shared drive members",
                description=(
                    "The primary admin cannot read who belongs to shared drives. "
                    "(HTTP 403)"
                ),
            ),
        ):
            drive_id: str | None = next(
                ops.list_drives(
                    user_email=auth.primary_admin_email,
                    use_domain_admin_access=is_admin,
                ),
                None,
            )
            if drive_id is not None:
                next(
                    ops.list_drive_members(
                        drive_id=drive_id, use_domain_admin_access=is_admin
                    ),
                    None,
                )
        if not is_admin:
            raise InsufficientPermissionsError(
                f"{auth.primary_admin_email} is not a Workspace admin, so group "
                "sync reads only the shared drives it is a member of.",
                summary=f"{auth.primary_admin_email} is not a Workspace admin",
                description=(
                    "Group sync reads only the shared drives the primary admin is "
                    "a member of."
                ),
            )
        if drive_id is None:
            raise NothingToCheckError(
                "The primary admin sees no shared drive, so there are no members "
                "to read.",
                summary="No shared drives to test",
                description="The primary admin sees no shared drive.",
            )
        return CheckOutput(
            summary=f"Members of {drive_id} readable",
            advisories=[
                CheckAdvisory(
                    message=(
                        "One shared drive's members are readable. Other drives "
                        "were not tested."
                    )
                )
            ],
        )


class _FolderPermissionsCheck(_GoogleDriveCheck):
    """Lists folders with their permissions as the primary admin, as group
    sync does for each user, and reads the permissions of a folder that has
    them only by id."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_folder_permissions",
            display_name="Read folder permissions",
            required=False,
            remediation=(
                "Give the service account the drive.metadata.readonly scope "
                "(OAuth: connect again and accept every permission). Without it, "
                "users get access only through each file's own permissions."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        ops: GoogleDriveSourceOperations = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list folders with their permissions",
            denied_row=_RowText(
                summary="Cannot list folders with permissions",
                description=(
                    "Google Drive refuses to list folders with who can open them. "
                    "(HTTP 403)"
                ),
            ),
        ):
            auth: GoogleDriveAuth = ops.authenticate()
            # The sync ends the listing quietly on a denial; the check reports it.
            folder: GoogleDriveFileType | None = next(
                ops.list_folders_with_permissions(
                    user_email=auth.primary_admin_email, continue_on_404_or_403=False
                ),
                None,
            )
        if folder is None:
            raise NothingToCheckError(
                "The primary admin sees no folder, so there are no folder "
                "permissions to read.",
                summary="No folders in scope",
                description="The primary admin sees no folder.",
            )
        name: str = folder.get("name") or folder["id"]
        readable: CheckOutput = CheckOutput(
            summary=f"Permissions of {name} readable",
            advisories=[
                CheckAdvisory(
                    message=(
                        "One folder's permissions are readable. Other folders were "
                        "not tested."
                    )
                )
            ],
        )
        if folder.get("permissions"):
            return readable
        if not folder.get("permissionIds"):
            raise InconclusiveValidationError(
                f"Google returned the folder '{name}' without any permissions or "
                "permission IDs.",
                summary="First folder listed without permissions",
                description=(
                    "Google returned the folder without any permissions or "
                    "permission IDs."
                ),
            )
        if not _read_permissions(context, ops, auth.primary_admin_email, folder):
            raise InsufficientPermissionsError(
                f"The credential cannot read who can open the folder '{name}', "
                "so its members do not get access through it.",
                summary=f"Cannot read who can open {name}",
                description=(
                    f"Members of {name} would get no access through the folder.\n"
                    f"{_scope_need(context)}"
                ),
            )
        return readable


def build_google_drive_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_FilePermissionsCheck()]


def build_google_drive_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _DirectoryAdminCheck(),
        _DirectoryUsersCheck(),
        _GroupsCheck(),
        _DriveMembershipCheck(),
        _FolderPermissionsCheck(),
    ]
