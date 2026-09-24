from collections.abc import Generator

from pydantic import ValidationError

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
)
from onyx.connectors.microsoft_utils.drive_items import build_delta_start_url
from onyx.connectors.onedrive.errors import (
    OneDriveAuthError,
    OneDriveGraphError,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.onedrive.models import (
    OneDriveConnectorConfig,
    OneDriveDrive,
    OneDriveUser,
)
from onyx.connectors.onedrive.scope import normalize_configured_users
from onyx.connectors.onedrive.source_operations import (
    GRAPH_API_VERSION,
    USERS_PAGE_SIZE,
    OneDriveSourceOperations,
)

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/onedrive"
_DELTA_PROBE_PAGE_SIZE = 1


def _gateway(context: CapabilityCheckContext) -> OneDriveSourceOperations:
    assert isinstance(context.source_operations, OneDriveSourceOperations)
    return context.source_operations


def _config(context: CapabilityCheckContext) -> OneDriveConnectorConfig:
    try:
        return OneDriveConnectorConfig.model_validate(
            context.connector_specific_config or {}
        )
    except ValidationError as error:
        raise ConnectorValidationError(
            f"Invalid OneDrive connector configuration: {error}"
        ) from error


def _configured_users(context: CapabilityCheckContext) -> list[str]:
    return normalize_configured_users(_config(context).users)


def _candidate_users(
    context: CapabilityCheckContext,
) -> Generator[OneDriveUser, None, None]:
    gateway = _gateway(context)
    config = _config(context)
    configured = normalize_configured_users(config.users)
    if not config.all_users:
        if not configured:
            raise ConnectorValidationError(
                "Select all users or list at least one user."
            )
        for identifier in configured:
            try:
                user = gateway.get_user(identifier=identifier)
            except OneDriveGraphError as error:
                if not error.is_permanent_refusal:
                    raise
                continue
            if user is not None:
                yield user
        return

    next_link: str | None = None
    while True:
        page = gateway.list_users(
            page_size=USERS_PAGE_SIZE,
            next_link=next_link,
        )
        yield from page.users
        next_link = page.next_link
        if next_link is None:
            return


def _candidate_drives(
    context: CapabilityCheckContext,
) -> Generator[OneDriveDrive, None, None]:
    gateway = _gateway(context)
    for user in _candidate_users(context):
        try:
            drive = gateway.get_default_drive(user_id=user.id)
        except OneDriveGraphError as error:
            if not error.is_permanent_refusal:
                raise
            continue
        if drive is not None:
            yield drive


class _TokenCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="onedrive_token_auth",
            display_name="App registration can sign in",
            requires_connector_instance=False,
            remediation="Check the app id, tenant id, and client credential.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).check_token()
        except OneDriveAuthError as error:
            raise_for_auth_error(error)
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "Microsoft refused the token request.")


class _UsersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="onedrive_users",
            display_name="Tenant users can be listed",
            requires_connector_instance=False,
            remediation="Grant and admin-consent `User.Read.All`.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).list_users(page_size=_DELTA_PROBE_PAGE_SIZE)
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot list tenant users.")


class _ConfiguredUsersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="onedrive_configured_users",
            display_name="Configured users resolve",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation="Use enabled member user principal names.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        for identifier in _configured_users(context):
            try:
                user = gateway.get_user(identifier=identifier)
            except OneDriveGraphError as error:
                raise_for_graph_error(error, f"The app cannot resolve `{identifier}`.")
            if user is None:
                raise ConnectorValidationError(f"No user matches `{identifier}`.")


class _DriveCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="onedrive_drive",
            display_name="A OneDrive is readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            if next(_candidate_drives(context), None) is None:
                raise ConnectorValidationError("No readable OneDrive was found.")
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot read this user's OneDrive.")


class _DeltaCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="onedrive_delta",
            display_name="OneDrive changes are readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        try:
            host = _config(context).graph_api_host.rstrip("/")
            for drive in _candidate_drives(context):
                try:
                    gateway.get_delta_page(
                        drive_id=drive.id,
                        page_url=build_delta_start_url(
                            f"{host}/{GRAPH_API_VERSION}",
                            drive.id,
                            page_size=_DELTA_PROBE_PAGE_SIZE,
                            select_fields=DRIVE_DELTA_SELECT_FIELDS,
                        ),
                        page_size=_DELTA_PROBE_PAGE_SIZE,
                    )
                except OneDriveGraphError as error:
                    if error.fails_the_attempt:
                        raise
                    continue
                return
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot read OneDrive changes.")
        raise ConnectorValidationError("No readable OneDrive delta was found.")


def build_onedrive_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _UsersCheck(),
        _ConfiguredUsersCheck(),
        _DriveCheck(),
        _DeltaCheck(),
    ]
