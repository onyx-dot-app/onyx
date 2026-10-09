"""Capability checks for the Google Drive connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
(one page, or the first in-scope item) with the gateway operations its sync
calls.

Two credential kinds need different checks (``credential_kinds``):

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
from typing import NoReturn

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
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
    list_drive_members,
    list_group_member_emails,
    select_drive_organizer,
)
from onyx.connectors.google_drive.models import GDriveMimeType, GoogleDriveFileType
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    ExportSizeThresholdExceeded,
    GoogleDriveAuth,
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
)
from onyx.connectors.models import ConnectorMissingCredentialError

_DOCS_LINK = SCOPE_DOC_URL
_SERVICE_ACCOUNT = frozenset({GoogleCredentialKind.SERVICE_ACCOUNT.value})
_OAUTH = frozenset({GoogleCredentialKind.OAUTH.value})

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

_DISABLED_API_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
_SCOPE_REASONS = frozenset(
    {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
)
_DOWNLOAD_BLOCKED_REASONS = frozenset({"cannotDownloadFile", "cannotExportFile"})


def _gateway(context: CapabilityCheckContext) -> GoogleDriveSourceOperations:
    gateway = context.source_operations
    if not isinstance(gateway, GoogleDriveSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _is_service_account(auth: GoogleDriveAuth) -> bool:
    return auth.kind == GoogleCredentialKind.SERVICE_ACCOUNT


def _scope_hint(context: CapabilityCheckContext) -> str:
    if context.credential_kind == GoogleCredentialKind.OAUTH.value:
        return "Connect Google Drive again and accept every permission Onyx asks for."
    scopes = ", ".join(GOOGLE_SCOPES[DocumentSource.GOOGLE_DRIVE])
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
    not_found: str | None = None,
) -> Iterator[None]:
    """Maps the gateway's errors onto the validation-exception family.
    ``api`` names the Google API the probe calls; ``denied`` explains a 403."""
    try:
        yield
    except (GoogleDriveRefreshError, GoogleDriveHttpError, PermissionError) as e:
        _raise_google_error(context, e, api=api, denied=denied, not_found=not_found)


def _raise_google_error(
    context: CapabilityCheckContext,
    error: Exception,
    *,
    api: str,
    denied: str,
    not_found: str | None = None,
) -> NoReturn:
    try:
        raise error
    except ConnectorMissingCredentialError as e:
        raise ConnectorValidationError(
            "The credential has no primary admin email. Edit the credential and set it."
        ) from e
    except GoogleDriveRefreshError as e:
        message = str(e)
        if MISSING_SCOPES_ERROR_STR in message or "unauthorized_client" in message:
            raise InsufficientPermissionsError(
                f"Google refused the scopes Onyx asks for. {_scope_hint(context)}"
            ) from e
        if context.credential_kind == GoogleCredentialKind.OAUTH.value:
            raise CredentialExpiredError(
                "Google refused the OAuth credential: it was revoked or it "
                "expired. Connect Google Drive again."
            ) from e
        admin = context.credential_json.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
        raise InsufficientPermissionsError(
            "Google refused to let the service account act as "
            f"{admin or 'the primary admin'}. Check that the user exists, is not "
            "suspended, and that domain-wide delegation is set up for the "
            f"service account ({_detail(e)})."
        ) from e
    except GoogleDriveHttpError as e:
        if e.status_code == 401:
            raise CredentialExpiredError(
                "Google rejected the credential (HTTP 401). It was revoked or it "
                "expired."
            ) from e
        if _DISABLED_API_REASONS.intersection(e.reasons):
            raise ConnectorValidationError(
                f"The {api} is turned off in the Google Cloud project of the "
                "credential. Turn it on in the Google Cloud console (APIs & "
                "Services > Library)."
            ) from e
        if _SCOPE_REASONS.intersection(e.reasons):
            raise InsufficientPermissionsError(
                f"The credential is missing a scope Onyx needs. {_scope_hint(context)}"
            ) from e
        if e.status_code == 429 or (e.status_code == 403 and not e.access_denied):
            raise UnexpectedValidationError(
                "Google rate limited the check. Run the checks again in a minute."
            ) from e
        if e.status_code == 403:
            raise InsufficientPermissionsError(f"{denied} (HTTP 403).") from e
        if e.status_code == 404 and not_found is not None:
            raise ConnectorValidationError(f"{not_found} (HTTP 404).") from e
        raise UnexpectedValidationError(
            f"Unexpected Google response (HTTP {e.status_code}): {_detail(e)}"
        ) from e
    except PermissionError as e:
        # get_google_creds: an invalid key, an unknown credential shape, or an
        # OAuth token that no longer refreshes.
        raise CredentialExpiredError(
            f"Google rejected the credential: {_detail(e)}"
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
    specific = extract_str_list_from_comma_str(config.specific_user_emails)
    if specific:
        return specific, False
    users = [auth.primary_admin_email]
    if not _is_service_account(auth):
        return users, False
    listed = list(islice(ops.list_user_emails(), _MAX_LISTED_USERS + 1))
    truncated = len(listed) > _MAX_LISTED_USERS
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
        metadata = ops.probe_target(user_email=email, target_id=target_id)
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
        credential_kinds: frozenset[str] | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            credential_kinds=credential_kinds,
            remediation=remediation,
            docs_link=_DOCS_LINK,
        )


class _AuthCheck(_GoogleDriveCheck):
    """Loads the credential and lists one file as the primary admin. A
    service account also opens the admin's My Drive, as each user's crawl
    does first."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_auth",
            display_name="Credential reads Google Drive as the primary admin",
            remediation=(
                "Service account: set up domain-wide delegation with the scopes "
                "in the Onyx docs, and use a Workspace user as the primary admin. "
                "OAuth: connect Google Drive again. Turn on the Google Drive API "
                "in the Google Cloud project of the credential."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=(
                "The credential signs in, but Google Drive does not let the "
                "primary admin list files"
            ),
        ):
            auth = ops.authenticate()
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


class _WorkspaceUsersCheck(_GoogleDriveCheck):
    """A service account lists the Workspace users to crawl each one's
    files."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_workspace_users",
            display_name="Workspace users can be listed",
            credential_kinds=_SERVICE_ACCOUNT,
            remediation=(
                "Make the primary admin a Google Workspace admin, give the service "
                "account the admin.directory.user.readonly scope in domain-wide "
                "delegation, and turn on the Admin SDK API. Or list the users to "
                "index in 'Specific user emails'."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return not form_state.config.specific_user_emails

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list the Workspace users",
        ):
            first_admin = next(ops.list_user_emails(query="isAdmin=true"), None)
        if first_admin is None:
            raise UnexpectedValidationError(
                "The Workspace directory listed no admin, so Onyx cannot verify "
                "the user listing."
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
                )
            # Indexing skips a user without Drive the same way.
            failures.append(f"{email} (has no Google Drive access)")
    return failures


class _SpecificUsersCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_specific_users",
            display_name="Listed users can be impersonated",
            required=False,
            requires_connector_config=True,
            credential_kinds=_SERVICE_ACCOUNT,
            remediation=(
                "Check the emails in 'Specific user emails': each must be the "
                "primary email of an active Workspace user with Google Drive."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return bool(form_state.config.specific_user_emails)

    def run(self, context: CapabilityCheckContext) -> None:
        emails = extract_str_list_from_comma_str(
            self.config(context).specific_user_emails
        )
        failures = _impersonation_failures(context, _gateway(context), emails)
        if failures:
            raise ConnectorValidationError(
                "Onyx cannot act as these users, so it skips their files: "
                f"{', '.join(failures)}."
            )


class _OAuthIgnoredSettingsCheck(_GoogleDriveCheck):
    """An OAuth credential reads as its own user only; the per-user settings
    do nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_oauth_user_settings",
            display_name="Settings apply to an OAuth credential",
            required=False,
            requires_connector_config=True,
            credential_kinds=_OAUTH,
            remediation=(
                "To index other users' My Drives, use a service account "
                "credential. Otherwise clear these settings."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        config = form_state.config
        return bool(config.my_drive_emails or config.specific_user_emails)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ignored = [
            name
            for name, value in (
                ("My Drive emails", config.my_drive_emails),
                ("Specific user emails", config.specific_user_emails),
            )
            if value
        ]
        raise ConnectorValidationError(
            f"An OAuth credential indexes only what its own user sees, so Onyx "
            f"ignores {' and '.join(ignored)}."
        )


class _SharedDrivesCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_shared_drives",
            display_name="Shared drives can be listed",
            requires_connector_config=True,
            remediation=(
                "Service account: make the primary admin a Workspace admin who "
                "can manage shared drives. OAuth: the connected user must be a "
                "member of the shared drives to index."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return _shared_drives_in_scope(form_state.config)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The primary admin cannot list the shared drives",
        ):
            auth = ops.authenticate()
            first_drive = next(
                ops.list_drives(
                    user_email=auth.primary_admin_email,
                    use_domain_admin_access=_is_service_account(auth),
                ),
                None,
            )
        if first_drive is None and not config.shared_drive_urls:
            # Not FAILED: the domain can have no shared drive yet.
            raise UnexpectedValidationError(
                "No shared drive is visible to the credential, so shared drives "
                "index nothing."
            )


class _ConfiguredSharedDrivesCheck(_GoogleDriveCheck):
    """A configured id that is not a shared drive is crawled as a folder; it
    must be visible to some user the connector acts as."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_shared_drives",
            display_name="Configured shared drives are visible",
            requires_connector_config=True,
            remediation=(
                "Use the URL of each shared drive (https://drive.google.com/drive/"
                "folders/<id>). Service account: an organizer of the drive must be "
                "a user Onyx indexes. OAuth: the connected user must be a member."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return bool(form_state.config.shared_drive_urls)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot read the configured shared drives",
        ):
            auth = ops.authenticate()
            visible = _visible_drive_ids(ops, auth)
            missing = [
                drive_id
                for drive_id in _shared_drive_ids(config)
                if drive_id not in visible
            ]
            if not missing:
                return
            candidates, truncated = _candidate_users(ops, auth, config)
            unreachable = [
                drive_id
                for drive_id in missing
                if _find_viewer(ops, candidates, drive_id) is None
            ]
        if unreachable and truncated:
            raise UnexpectedValidationError(
                f"No shared drive with the IDs {', '.join(unreachable)} is "
                f"visible to the first {_MAX_LISTED_USERS} users, so Onyx cannot "
                "verify them."
            )
        if unreachable:
            raise ConnectorValidationError(
                f"Nothing with the IDs {', '.join(unreachable)} is visible to the "
                "credential. Onyx cannot index them, and it does not prune the "
                "connector while they stay out of reach."
            )


class _ConfiguredFoldersCheck(_GoogleDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_folders",
            display_name="Configured folders are visible",
            requires_connector_config=True,
            remediation=(
                "Use the URL of each folder (https://drive.google.com/drive/"
                "folders/<id>). Put shared drive URLs in 'Shared drive URLs'. "
                "Share each folder with a user Onyx indexes."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return bool(form_state.config.shared_folder_urls)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ops = _gateway(context)
        problems: list[str] = []
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot read the configured folders",
        ):
            auth = ops.authenticate()
            visible_drives = _visible_drive_ids(ops, auth)
            requested_drives = set(_shared_drive_ids(config))
            candidates, truncated = _candidate_users(ops, auth, config)
            listed = False
            for folder_id in _folder_ids(config):
                if folder_id in visible_drives:
                    # The connector drops a drive id from the folders.
                    if folder_id not in requested_drives:
                        problems.append(
                            f"{folder_id} is a shared drive; put its URL in "
                            "'Shared drive URLs'"
                        )
                    continue
                found = _find_viewer(ops, candidates, folder_id)
                if found is None:
                    problems.append(f"{folder_id} is not visible to the credential")
                    continue
                viewer, metadata = found
                if metadata.get("mimeType") != DRIVE_FOLDER_TYPE:
                    problems.append(f"{folder_id} is a file, not a folder")
                    continue
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
        if problems and truncated and all("not visible" in p for p in problems):
            raise UnexpectedValidationError(
                f"{'; '.join(problems)} among the first {_MAX_LISTED_USERS} users, "
                "so Onyx cannot verify them."
            )
        if problems:
            raise ConnectorValidationError(
                f"Onyx cannot index these folders: {'; '.join(problems)}."
            )


class _ConfiguredMyDrivesCheck(_GoogleDriveCheck):
    """A My Drive email must be the primary email of a listed user: indexing
    skips any other email (an alias, a typo) without an error."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_configured_my_drives",
            display_name="Configured My Drive users exist",
            requires_connector_config=True,
            credential_kinds=_SERVICE_ACCOUNT,
            remediation=(
                "Use each user's primary Workspace email, not an alias. With "
                "'Specific user emails' set, each My Drive email must also be in "
                "that list."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return bool(form_state.config.my_drive_emails)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ops = _gateway(context)
        requested = extract_str_list_from_comma_str(config.my_drive_emails)
        with _google_errors(
            context, api=_ADMIN_API, denied="The primary admin cannot list users"
        ):
            auth = ops.authenticate()
            users, truncated = _candidate_users(ops, auth, config)
        known = {email.lower() for email in users}
        found = [email for email in requested if email.lower() in known]
        missing = [email for email in requested if email.lower() not in known]
        if missing and truncated:
            raise UnexpectedValidationError(
                f"{', '.join(missing)} are not among the first {_MAX_LISTED_USERS} "
                "users, so Onyx cannot verify them."
            )
        if missing:
            raise ConnectorValidationError(
                f"Onyx skips these My Drives: {', '.join(missing)} are not "
                "primary emails of the users it indexes."
            )
        failures = _impersonation_failures(context, ops, found)
        if failures:
            raise ConnectorValidationError(
                f"Onyx cannot act as these users: {', '.join(failures)}."
            )
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=f"Google Drive does not let {found[0]} list files",
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


class _SharedDriveOrganizerCheck(_GoogleDriveCheck):
    """A service account reads each shared drive as an organizer, the one role
    that sees folders with limited access. Probes the first drive in scope."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_shared_drive_organizer",
            display_name="Shared drives have an organizer Onyx can act as",
            required=False,
            requires_connector_config=True,
            credential_kinds=_SERVICE_ACCOUNT,
            remediation=(
                "Make a Workspace user a Manager of each shared drive, and keep "
                "that user in the users Onyx indexes. Without one, Onyx can miss "
                "folders with limited access."
            ),
        )

    def applies(self, form_state: FormState[GoogleDriveConnectorConfig]) -> bool:
        return _shared_drives_in_scope(form_state.config)

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied=(
                "Onyx cannot read the members of a shared drive, so it reads "
                "shared drives as the primary admin and can miss folders with "
                "limited access"
            ),
        ):
            auth = ops.authenticate()
            visible = _visible_drive_ids(ops, auth)
            configured = [
                drive_id
                for drive_id in _shared_drive_ids(config)
                if drive_id in visible
            ]
            drive_id = next(iter(configured or sorted(visible)), None)
            if drive_id is None:
                # google_drive_shared_drives reports no visible drive.
                return
            choice = select_drive_organizer(
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
                    "the admin can see it."
                )
            if not choice.complete:
                role = choice.role.value if choice.role else "member"
                raise ConnectorValidationError(
                    f"Shared drive {drive_id} has no organizer Onyx can act as, so "
                    f"Onyx reads it as {choice.email} ({role}) and can miss folders "
                    "with limited access."
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
            display_name="File content can be downloaded",
            required=False,
            remediation=(
                "Give the service account the drive.readonly scope (OAuth: "
                "connect again and accept every permission). A file owner can "
                "also block downloads for viewers; Onyx skips those files."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list files",
        ):
            auth = ops.authenticate()
            files = _sample_files(
                ops,
                auth.primary_admin_email,
                f"mimeType != '{DRIVE_FOLDER_TYPE}' and "
                f"mimeType != '{DRIVE_SHORTCUT_TYPE}' and trashed = false",
            )
        native = next(
            (
                file
                for file in files
                if file.get("mimeType") in GOOGLE_MIME_TYPES_TO_EXPORT
            ),
            None,
        )
        uploaded = [
            (size, file)
            for file in files
            if file.get("mimeType") not in GOOGLE_MIME_TYPES_TO_EXPORT
            and (size := _size(file)) is not None
            and size <= _MAX_PROBE_BYTES
        ]
        smallest = min(uploaded, key=lambda item: item[0])[1] if uploaded else None
        for file in (native, smallest):
            if file is not None:
                self._read(context, ops, auth, file)

    def _read(
        self,
        context: CapabilityCheckContext,
        ops: GoogleDriveSourceOperations,
        auth: GoogleDriveAuth,
        file: GoogleDriveFileType,
    ) -> None:
        name = file.get("name") or file["id"]
        mime_type = file.get("mimeType")
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
                raise ConnectorValidationError(
                    f"The owner of '{name}' blocked downloads for viewers, so "
                    "Onyx skips files like it."
                ) from e
            _raise_google_error(
                context,
                e,
                api=_DRIVE_API,
                denied=f"The credential can see '{name}' but cannot download it",
            )
        except GoogleDriveRefreshError as e:
            _raise_google_error(context, e, api=_DRIVE_API, denied="")


class _DocsApiCheck(_GoogleDriveCheck):
    """Reads one Google Doc through the Docs API, which gives indexed Docs
    their heading links. Passes when the primary admin sees no Google Doc."""

    def __init__(self) -> None:
        super().__init__(
            check_id="google_drive_docs_api",
            display_name="Google Docs API is on",
            required=False,
            remediation=(
                "Turn on the Google Docs API in the Google Cloud project of the "
                "credential. Without it, Google Docs index without links to their "
                "headings."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DOCS_API,
            denied="The credential cannot read Google Docs through the Docs API",
        ):
            auth = ops.authenticate()
            docs = _sample_files(
                ops,
                auth.primary_admin_email,
                f"mimeType = '{GDriveMimeType.DOC.value}' and trashed = false",
            )
            if not docs:
                return
            ops.fetch_google_doc(
                user_email=auth.primary_admin_email,
                doc_id=docs[0]["id"],
                max_response_bytes=_MAX_PROBE_BYTES,
            )


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
_DIRECTORY_HINT = (
    "Make the primary admin a Google Workspace admin. Service account: give it "
    "the admin.directory.user.readonly and admin.directory.group.readonly "
    "scopes in domain-wide delegation. Turn on the Admin SDK API."
)


def _read_permissions(
    context: CapabilityCheckContext,
    ops: GoogleDriveSourceOperations,
    user_email: str,
    item: GoogleDriveFileType,
    kind: str,
) -> None:
    """Reads the permissions of a file or folder that lists them only by id,
    as the sync does. Fails when none comes back."""
    name = item.get("name") or item["id"]
    with _google_errors(
        context,
        api=_DRIVE_API,
        denied=f"The credential cannot read who can open the {kind} '{name}'",
    ):
        permissions = list(
            ops.list_file_permissions(
                user_email=user_email, file_id=item["id"], fields=_PERMISSION_FIELDS
            )
        )
    if not permissions:
        raise InsufficientPermissionsError(
            f"Google Drive returned no permissions for the {kind} '{name}', so "
            "Onyx cannot tell who can open it."
        )


class _FilePermissionsCheck(_GoogleDriveCheck):
    """Lists files with their permissions as the primary admin, and reads the
    permissions of a file that has them only by id. Passes when every sampled
    file carries its permissions."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="google_drive_file_permissions",
            display_name="File permissions are readable",
            remediation=(
                "Give the service account the drive.readonly and "
                "drive.metadata.readonly scopes (OAuth: connect again and accept "
                "every permission)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list files with their permissions",
        ):
            auth = ops.authenticate()
            files = _files(
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
        by_id_only = next(
            (
                file
                for file in files
                if file.get("permissionIds") and not file.get("permissions")
            ),
            None,
        )
        if by_id_only is not None:
            _read_permissions(
                context, ops, auth.primary_admin_email, by_id_only, "file"
            )
            return
        if files and not any(file.get("permissions") for file in files):
            raise InsufficientPermissionsError(
                "Google Drive listed files without their permissions, so Onyx "
                "cannot tell who can open them. Give the credential the "
                "drive.metadata.readonly scope."
            )


class _DirectoryAdminCheck(_GoogleDriveCheck):
    """Reads the primary admin's directory entry, as group sync does first."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_directory_admin",
            display_name="Primary admin can use the Workspace directory",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        admin = context.credential_json.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied=(
                f"Primary admin {admin or ''} is not authorized on the Google "
                "Workspace directory API. Reconnect the connector with an "
                "account that has admin directory access"
            ),
        ):
            ops.authenticate()
            ops.get_admin_user()


class _DirectoryUsersCheck(_GoogleDriveCheck):
    """Group sync puts every listed user in the group of the Workspace domain,
    which "anyone at the domain" shares grant."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_directory_users",
            display_name="Workspace users can be listed",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot list the Workspace users",
        ):
            ops.authenticate()
            first_user = next(ops.list_user_emails(), None)
        if first_user is None:
            raise UnexpectedValidationError(
                "The Workspace directory listed no user, so Onyx cannot verify "
                "the user listing."
            )


class _GroupsCheck(_GoogleDriveCheck):
    """Lists the groups and reads the members of the first. Passes when the
    domain has no group."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_groups",
            display_name="Groups and their members are readable",
            remediation=_DIRECTORY_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_ADMIN_API,
            denied="The primary admin cannot read the Workspace groups",
        ):
            ops.authenticate()
            first_group = next(ops.list_groups(), None)
            if first_group is None:
                return
            next(ops.list_group_members(group_email=first_group), None)


class _DriveMembershipCheck(_GoogleDriveCheck):
    """Reads the members of the first shared drive, as group sync reads every
    drive. A primary admin who is not a Workspace admin reads only the drives
    it is a member of."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_shared_drive_members",
            display_name="Shared drive members are readable",
            required=False,
            remediation=(
                "Make the primary admin a Workspace admin who can manage shared "
                "drives. Without it, users get access to shared drive files only "
                "through the files' own permissions."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The primary admin cannot read the members of shared drives",
        ):
            auth = ops.authenticate()
            admin_user = ops.get_admin_user()
            is_admin = admin_user.is_admin or admin_user.is_delegated_admin
            drive_id = next(
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
                "sync reads only the shared drives it is a member of."
            )


class _FolderPermissionsCheck(_GoogleDriveCheck):
    """Lists folders with their permissions as the primary admin, as group
    sync does for each user, and reads the permissions of a folder that has
    them only by id."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="google_drive_folder_permissions",
            display_name="Folder permissions are readable",
            required=False,
            remediation=(
                "Give the service account the drive.metadata.readonly scope "
                "(OAuth: connect again and accept every permission). Without it, "
                "users get access only through each file's own permissions."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        ops = _gateway(context)
        with _google_errors(
            context,
            api=_DRIVE_API,
            denied="The credential cannot list folders with their permissions",
        ):
            auth = ops.authenticate()
            folder = next(
                ops.list_folders_with_permissions(user_email=auth.primary_admin_email),
                None,
            )
        if folder is None or folder.get("permissions"):
            return
        if folder.get("permissionIds"):
            _read_permissions(context, ops, auth.primary_admin_email, folder, "folder")


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
