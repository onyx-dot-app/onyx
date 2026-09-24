from collections.abc import Callable, Generator
from typing import TypeVar

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
    DriveDeltaItem,
    build_delta_start_url,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OneDriveAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.onedrive.models import (
    OneDriveConnectorConfig,
    OneDriveDrive,
    OneDriveGroup,
    OneDriveUser,
    OneDriveUserPage,
)
from onyx.connectors.onedrive.scope import normalize_configured_users
from onyx.connectors.onedrive.source_operations import (
    GRAPH_API_VERSION,
    OneDriveSourceOperations,
)

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/onedrive"
_PROBE_PAGE_SIZE = 1
_CANDIDATE_PAGES = 20

T = TypeVar("T")
_MAX_DISCOVERY_PAGES = 20
_HIDDEN_MEMBERSHIP_VISIBILITY = "HiddenMembership"
_MEMBER_READ_HIDDEN_SCOPE = "Member.Read.Hidden"


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
    if configured:
        for identifier in configured[:_CANDIDATE_PAGES]:
            try:
                user = gateway.get_user(identifier=identifier)
            except OneDriveGraphError as error:
                if not error.is_permanent_refusal:
                    raise
                if error.status == 403:
                    raise
                continue
            if user is not None:
                yield user
        return

    next_link: str | None = None
    for _ in range(_CANDIDATE_PAGES):
        page = gateway.list_users(
            page_size=_PROBE_PAGE_SIZE,
            next_link=next_link,
        )
        if not isinstance(page, OneDriveUserPage):
            continue
        if page.users:
            yield page.users[0]
        next_link = page.next_link
        if next_link is None:
            return


def _first_drive_that(
    context: CapabilityCheckContext,
    opens: Callable[[OneDriveDrive], T | None],
    denied_message: str,
    nothing_to_probe: str,
) -> tuple[OneDriveDrive, T]:
    gateway = _gateway(context)
    denied: OneDriveGraphError | None = None
    for user in _candidate_users(context):
        try:
            drive = gateway.get_default_drive(user_id=user.id)
        except OneDriveGraphError as error:
            if not error.is_permanent_refusal:
                raise
            if error.status == 403:
                denied = error
            continue
        if drive is None:
            continue
        try:
            opened = opens(drive)
        except OneDriveGraphError as error:
            if error.fails_the_attempt:
                raise
            if error.status == 403:
                denied = error
            continue
        if opened is not None:
            return drive, opened
    if denied is not None:
        raise_for_graph_error(denied, denied_message)
    raise ConnectorValidationError(nothing_to_probe)


def _first_delta_item(
    gateway: OneDriveSourceOperations,
    drive: OneDriveDrive,
    start_url: str,
) -> DriveDeltaItem | None:
    cursor: str | None = start_url
    for _ in range(_MAX_DISCOVERY_PAGES):
        assert cursor is not None
        result = gateway.get_delta_page(
            drive_id=drive.id,
            page_url=cursor,
            page_size=_PROBE_PAGE_SIZE,
        )
        item = next(
            (item for item in result.page.items if not item.is_tombstone),
            None,
        )
        if item is not None:
            return item
        cursor = result.next_cursor
        if cursor is None:
            return None
    raise ConnectorValidationError(
        f"No readable OneDrive item was found in {_MAX_DISCOVERY_PAGES} delta pages."
    )


def _probe_item_permissions(
    gateway: OneDriveSourceOperations,
    drive: OneDriveDrive,
    graph_api_base: str,
) -> bool:
    item = _first_delta_item(
        gateway,
        drive,
        build_delta_start_url(
            graph_api_base,
            drive.id,
            page_size=_PROBE_PAGE_SIZE,
            select_fields=DRIVE_DELTA_SELECT_FIELDS,
        ),
    )
    if item is not None:
        gateway.list_permissions(drive_id=drive.id, item_id=item.id)
    return True


def _group_membership_probe_group(
    gateway: OneDriveSourceOperations,
) -> OneDriveGroup | None:
    representative: OneDriveGroup | None = None
    next_link: str | None = None
    for _ in range(_MAX_DISCOVERY_PAGES):
        page = gateway.list_groups(
            page_size=_PROBE_PAGE_SIZE,
            next_link=next_link,
        )
        if representative is None and page.groups:
            representative = page.groups[0]
        hidden_group = next(
            (
                group
                for group in page.groups
                if group.visibility == _HIDDEN_MEMBERSHIP_VISIBILITY
            ),
            None,
        )
        if hidden_group is not None:
            return hidden_group
        next_link = page.next_link
        if next_link is None:
            return representative
    return representative


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
            _gateway(context).list_users(page_size=_PROBE_PAGE_SIZE)
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
            _first_drive_that(
                context,
                lambda drive: drive,
                "The app cannot read the tenant's first OneDrives.",
                "No readable OneDrive was found among the first users.",
            )
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
            _first_drive_that(
                context,
                lambda drive: gateway.get_delta_page(
                    drive_id=drive.id,
                    page_url=build_delta_start_url(
                        f"{host}/{GRAPH_API_VERSION}",
                        drive.id,
                        page_size=_PROBE_PAGE_SIZE,
                        select_fields=DRIVE_DELTA_SELECT_FIELDS,
                    ),
                    page_size=_PROBE_PAGE_SIZE,
                ),
                "The app cannot read changes in the tenant's first OneDrives.",
                "No readable OneDrive delta was found among the first users.",
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot read OneDrive changes.")


class _PermissionCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="onedrive_item_permissions",
            display_name="OneDrive item permissions are readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        host = _config(context).graph_api_host.rstrip("/")
        try:
            _first_drive_that(
                context,
                lambda drive: _probe_item_permissions(
                    gateway,
                    drive,
                    f"{host}/{GRAPH_API_VERSION}",
                ),
                "The app cannot read permissions in the tenant's first OneDrives.",
                "No readable OneDrive was found among the first users.",
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot read OneDrive permissions.")


class _GroupListCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="onedrive_groups",
            display_name="Entra groups are readable",
            requires_connector_instance=False,
            remediation="Grant and admin-consent `GroupMember.ReadBasic.All`.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).list_groups(page_size=_PROBE_PAGE_SIZE)
        except OneDriveGraphError as error:
            raise_for_graph_error(error, "The app cannot list Entra groups.")


class _GroupMembershipCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="onedrive_group_members",
            display_name="Entra transitive group members are readable",
            requires_connector_instance=False,
            remediation=(
                "Grant `GroupMember.ReadBasic.All` and grant "
                f"`{_MEMBER_READ_HIDDEN_SCOPE}` for hidden membership."
            ),
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        try:
            group = _group_membership_probe_group(gateway)
            if group is None:
                return
            gateway.list_transitive_group_members(group_id=group.id)
        except OneDriveGraphError as error:
            denied = "The app cannot expand transitive Entra group members."
            if error.status == 403:
                denied += f" Hidden groups require `{_MEMBER_READ_HIDDEN_SCOPE}`."
            raise_for_graph_error(error, denied)


def build_onedrive_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _UsersCheck(),
        _ConfiguredUsersCheck(),
        _DriveCheck(),
        _DeltaCheck(),
    ]


def build_onedrive_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_PermissionCheck()]


def build_onedrive_group_sync_checks() -> list[CapabilityCheck]:
    return [_GroupListCheck(), _GroupMembershipCheck()]
