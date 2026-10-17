"""Capability checks for the OneDrive connector.

Each check makes small probes (one user, one drive, one delta page, one
group) with the gateway operations indexing and the syncs call. The drive
checks walk candidate users: the first configured users Graph finds, else
one user from each of the first pages of the tenant's user listing.

"Find selected users" is a partial find: when some are missing it is
INCOMPLETE, and the drive checks after it walk the users it found.
"""

from collections.abc import Callable, Generator
from typing import NoReturn, TypeVar

from pydantic import BaseModel

from onyx.connectors.capability_checks.findings import bounded_count
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckFindingKey,
    CheckOutput,
    CountFinding,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.check_text import (
    ENTRA_GROUPS_DENIED_ROW,
    grant_line,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
    DriveDeltaItem,
    build_delta_start_url,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.microsoft_utils.graph_errors import raise_for_graph_error
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftRowText,
    MicrosoftSignIn,
)
from onyx.connectors.microsoft_utils.sign_in import sign_in
from onyx.connectors.onedrive.config import OneDriveConnectorConfig
from onyx.connectors.onedrive.models import (
    OneDriveDrive,
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
# A bound on the pages the drive count reads. Pages hold up to 999 users, so
# the count reaches its cap long before this unless Graph sends empty pages.
_COUNT_PAGES = 20
# The longest row line the card shows.
_MAX_LINE = 40
_LOCKED_STATUS = 423

T = TypeVar("T")
_HIDDEN_MEMBERSHIP_VISIBILITY = "HiddenMembership"
_ACCOUNT_LABELS = MicrosoftAccountLabels.with_prefix(
    "OneDrive", private_key="OneDrive Certificate"
)
_USERS_GRANT_LINE = "Grant `User.Read.All` and admin-consent it."
_RETRY_LINE = "Re-run the checks. If it repeats, send the error details to support."

_SIGN_IN_CHECK_ID = "onedrive_token_auth"
_USERS_CHECK_ID = "onedrive_users"
_CONFIGURED_USERS_CHECK_ID = "onedrive_configured_users"
_DRIVE_CHECK_ID = "onedrive_drive"
_GROUPS_CHECK_ID = "onedrive_groups"
# check_id to the checks it runs after, in run order.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _USERS_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    "onedrive_drive_count": (_SIGN_IN_CHECK_ID,),
    _CONFIGURED_USERS_CHECK_ID: (_USERS_CHECK_ID,),
    # The selected users too: with none found there is no OneDrive to open.
    _DRIVE_CHECK_ID: (_USERS_CHECK_ID, _CONFIGURED_USERS_CHECK_ID),
    "onedrive_delta": (_DRIVE_CHECK_ID,),
    "onedrive_item_permissions": (_DRIVE_CHECK_ID,),
    _GROUPS_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    "onedrive_group_members": (_GROUPS_CHECK_ID,),
}


def _line(prefix: str, name: str, suffix: str = "") -> str:
    """``prefix``, ``name`` and ``suffix``, with the name cut to fit the row."""
    room: int = _MAX_LINE - len(prefix) - len(suffix)
    cut: str = name if len(name) <= room else name[: room - 1] + "…"
    return f"{prefix}{cut}{suffix}"


def _row(summary: str, description: str) -> MicrosoftRowText:
    return MicrosoftRowText(summary=summary, description=description)


_USERS_DENIED_ROW = _row(
    "No permission to read user directory",
    f"Every-user mode and user lookups would not work.\n{_USERS_GRANT_LINE}",
)
_USER_LIST_UNENDING_ROW = _row(
    "User list did not end",
    "Microsoft kept returning short pages.\nRe-run the checks later.",
)
_BLANK_USERS_ROW = _row(
    "Users holds only blank entries",
    "Specific scope is chosen but no user address is filled in.\nAdd at least one "
    "address to Users, or choose General.",
)
_DRIVES_DENIED_ROW = _row(
    "No permission to read sampled OneDrives",
    f"The app is refused on every OneDrive it tried.\n{grant_line('Sites.Read.All')}",
)
_GROUP_MEMBERS_DENIED_ROW = _row(
    "No permission to read group members",
    "The app cannot read who is in an Entra group.\n"
    + grant_line("GroupMember.Read.All"),
)
_NO_DRIVE_ROW = _row(
    "No OneDrives found to test",
    "None of the sampled users has a OneDrive the app could open.\nSelect users "
    "who have a OneDrive in Users, then run the checks again.",
)


class _NoCandidateFound(InconclusiveValidationError):
    pass


def _gateway(context: CapabilityCheckContext) -> OneDriveSourceOperations:
    if not isinstance(context.source_operations, OneDriveSourceOperations):
        raise TypeError("OneDrive checks need the OneDrive gateway.")
    return context.source_operations


def _config(context: CapabilityCheckContext) -> OneDriveConnectorConfig:
    # The runner fails a config-reading check before ``run`` when the config
    # has an invalid field.
    return form_config(context, OneDriveConnectorConfig)


def _raise_row(message: str, row: MicrosoftRowText) -> NoReturn:
    raise ConnectorValidationError(
        message, summary=row.summary, description=row.description
    )


def _is_invalid_entry(user: str) -> bool:
    if not user.strip():
        return False
    try:
        normalize_configured_users([user])
    except ConnectorValidationError:
        return True
    return False


def _configured_users(context: CapabilityCheckContext) -> list[str]:
    """The Users entries, normalized as indexing reads them. An entry that is
    not an email, or a list of blanks, fails with its row."""
    users: list[str] = _config(context).users or []
    try:
        return normalize_configured_users(users)
    except ConnectorValidationError as error:
        if not any(user.strip() for user in users):
            _raise_row(error.message, _BLANK_USERS_ROW)
        entry: str = next(
            (user.strip() for user in users if _is_invalid_entry(user)), ""
        )
        _raise_row(
            error.message,
            _row(
                _line("Not an email address: ", entry),
                "Each entry in Users must be a user principal name or primary "
                "email address.",
            ),
        )


def _candidate_users(
    context: CapabilityCheckContext,
) -> Generator[OneDriveUser, None, None]:
    gateway = _gateway(context)
    configured = _configured_users(context)
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


class _Opened(BaseModel):
    """The user whose OneDrive answered a probe."""

    user: OneDriveUser
    drive: OneDriveDrive


def _first_drive_that(
    context: CapabilityCheckContext,
    opens: Callable[[OneDriveDrive], T | None],
    denied_message: str,
    nothing_to_probe: MicrosoftRowText,
) -> tuple[_Opened, T]:
    """The first candidate's OneDrive on which ``opens`` returns something.
    A 403 is remembered: when nothing opens it is the likelier cause."""
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
            return _Opened(user=user, drive=drive), opened
    if denied is not None:
        raise_for_graph_error(denied, denied_message, denied_row=_DRIVES_DENIED_ROW)
    raise _NoCandidateFound(
        nothing_to_probe.description.split("\n", 1)[0],
        summary=nothing_to_probe.summary,
        description=nothing_to_probe.description,
    )


def _user_name(user: OneDriveUser) -> str:
    return user.display_name or user.user_principal_name


def _first_delta_item(
    gateway: OneDriveSourceOperations,
    drive: OneDriveDrive,
    start_url: str,
) -> DriveDeltaItem | None:
    cursor: str | None = start_url
    for _ in range(_CANDIDATE_PAGES):
        if cursor is None:
            return None
        result = gateway.get_delta_page(
            drive_id=drive.id,
            page_url=cursor,
            page_size=_PROBE_PAGE_SIZE,
            allow_full_resync=True,
        )
        item = next(
            (item for item in result.page.items if not item.is_tombstone),
            None,
        )
        if item is not None:
            return item
        cursor = result.next_checkpoint_url
    raise InconclusiveValidationError(
        f"No readable OneDrive item was found in {_CANDIDATE_PAGES} delta pages.",
        summary="No files found to test",
        description=(
            "The change feed of a OneDrive held only deleted items in its first pages."
        ),
    )


def _probe_item_permissions(
    gateway: OneDriveSourceOperations,
    drive: OneDriveDrive,
    graph_api_base: str,
) -> bool | None:
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
    if item is None:
        return None
    gateway.list_permissions(drive_id=drive.id, item_id=item.id)
    return True


def _group_membership_probe_group(
    gateway: OneDriveSourceOperations,
) -> EntraGroup | None:
    next_link: str | None = None
    for _ in range(_CANDIDATE_PAGES):
        page = gateway.list_groups(
            page_size=_PROBE_PAGE_SIZE,
            next_link=next_link,
        )
        visible_group = next(
            (
                group
                for group in page.items
                if group.visibility != _HIDDEN_MEMBERSHIP_VISIBILITY
            ),
            None,
        )
        if visible_group is not None:
            return visible_group
        next_link = page.next_link
        if next_link is None:
            return None
    return None


class _OneDriveCheck(CapabilityCheck[OneDriveConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_connector_config: bool = False,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
        discovery: bool = False,
        row_id: str | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            discovery=discovery,
            row_id=row_id,
        )


class _ConfigReadingCheck(_OneDriveCheck):
    config_class = OneDriveConnectorConfig


class _TokenCheck(_OneDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_SIGN_IN_CHECK_ID,
            display_name="Sign in to Microsoft",
            remediation="Check the app id, tenant id, and client credential.",
            validates_binding=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        signed_in: MicrosoftSignIn = sign_in(
            _gateway(context).check_token, _ACCOUNT_LABELS
        )
        return CheckOutput(
            summary=signed_in.summary,
            description=signed_in.description,
            advisories=[CheckAdvisory(message=caveat) for caveat in signed_in.caveats],
        )


class _UsersCheck(_OneDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_USERS_CHECK_ID,
            display_name="List users",
            remediation="Grant and admin-consent `User.Read.All`.",
            validates_binding=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            _gateway(context).list_users(page_size=_PROBE_PAGE_SIZE)
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot list tenant users.",
                denied_row=_USERS_DENIED_ROW,
                request="the user listing",
            )
        return CheckOutput(summary="Tenant user list is readable")


def _tenant_users(
    gateway: OneDriveSourceOperations,
) -> Generator[OneDriveUser, None, None]:
    """The tenant's enabled member users, read one page at a time."""
    next_link: str | None = None
    for _ in range(_COUNT_PAGES):
        page: OneDriveUserPage = gateway.list_users(next_link=next_link)
        yield from page.users
        next_link = page.next_link
        if next_link is None:
            return
    raise InconclusiveValidationError(
        f"The tenant's user listing did not end within {_COUNT_PAGES} pages.",
        summary=_USER_LIST_UNENDING_ROW.summary,
        description=_USER_LIST_UNENDING_ROW.description,
    )


class _DriveCountCheck(_ConfigReadingCheck):
    """Counts the enabled member users: the owners of the OneDrives indexing
    walks in every-user mode. It does not open each drive, so a user without a
    OneDrive still counts. It shares the "List users" row, whose probe reads
    one user. A config that lists users walks only those, so the tenant count
    does not apply to it."""

    def __init__(self) -> None:
        super().__init__(
            check_id="onedrive_drive_count",
            display_name="List users",
            remediation="Grant and admin-consent `User.Read.All`.",
            discovery=True,
            row_id=_USERS_CHECK_ID,
        )

    def applies(self, form_state: FormState[OneDriveConnectorConfig]) -> bool:
        return not [user for user in form_state.config.users or [] if user.strip()]

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            finding: CountFinding = bounded_count(
                _tenant_users(_gateway(context)),
                key=CheckFindingKey.READABLE_DRIVES,
                cap=MAX_FINDING_OPTIONS,
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot list tenant users.",
                denied_row=_USERS_DENIED_ROW,
                request="the user listing",
            )
        count: str = f"{finding.count}+" if finding.at_least else str(finding.count)
        return CheckOutput(
            summary=f"Up to {count} {'OneDrive' if count == '1' else 'OneDrives'}",
            findings=[finding],
        )


class _UserProblem(BaseModel):
    identifier: str
    message: str
    locked: bool


def _user_problem_row(problem: _UserProblem) -> MicrosoftRowText:
    if problem.locked:
        return _row(
            _line("User is locked: ", problem.identifier),
            f"Microsoft refused this user's lookup.\n{_RETRY_LINE}",
        )
    return _row(
        _line("User not found: ", problem.identifier),
        "No enabled member user has this address.\nCorrect or remove "
        f"{problem.identifier} in Users.",
    )


def _users_output(identifiers: list[str], problems: list[_UserProblem]) -> CheckOutput:
    if not problems:
        return CheckOutput(
            summary=(
                "1 selected user found"
                if len(identifiers) == 1
                else f"All {len(identifiers)} selected users found"
            )
        )
    message: str = " ".join(problem.message for problem in problems)
    first: MicrosoftRowText = _user_problem_row(problems[0])
    names: str = ", ".join(problem.identifier for problem in problems)
    if len(problems) == len(identifiers):
        if all(problem.locked for problem in problems):
            raise UnexpectedValidationError(
                message, summary=first.summary, description=first.description
            )
        _raise_row(
            message,
            first
            if len(problems) == 1
            else _row(
                "No selected user found",
                "None of the selected users is visible to this account.\nNot "
                f"found: {names}.",
            ),
        )
    if len(problems) == 1:
        return CheckOutput(
            summary=first.summary, description=first.description, partial=True
        )
    return CheckOutput(
        summary=f"{len(problems)} of {len(identifiers)} users not found",
        description=f"Not found: {names}.\nCorrect or remove them in Users.",
        partial=True,
    )


class _ConfiguredUsersCheck(_ConfigReadingCheck):
    """Every Users entry names an enabled member user. Some missing is
    INCOMPLETE, and the drive checks walk the found ones; none found
    FAILS."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_CONFIGURED_USERS_CHECK_ID,
            display_name="Find selected users",
            remediation="Use enabled member user principal names.",
            requires_connector_config=True,
        )

    def applies(self, form_state: FormState[OneDriveConnectorConfig]) -> bool:
        return bool(form_state.config.users)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = _gateway(context)
        identifiers: list[str] = _configured_users(context)
        problems: list[_UserProblem] = []
        for identifier in identifiers:
            try:
                user = gateway.get_user(identifier=identifier)
            except OneDriveGraphError as error:
                if error.status != _LOCKED_STATUS:
                    raise_for_graph_error(
                        error,
                        f"The app cannot resolve `{identifier}`.",
                        denied_row=_USERS_DENIED_ROW,
                        request="the user lookup",
                    )
                problems.append(
                    _UserProblem(
                        identifier=identifier,
                        message=f"The app cannot resolve `{identifier}` ({error.code}).",
                        locked=True,
                    )
                )
                continue
            if user is None:
                problems.append(
                    _UserProblem(
                        identifier=identifier,
                        message=f"No user matches `{identifier}`.",
                        locked=False,
                    )
                )
        return _users_output(identifiers, problems)


class _DriveCheck(_ConfigReadingCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_DRIVE_CHECK_ID,
            display_name="Find a OneDrive",
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            requires_connector_config=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            opened, _ = _first_drive_that(
                context,
                lambda drive: drive,
                "The app cannot read the tenant's first OneDrives.",
                _NO_DRIVE_ROW,
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot read this user's OneDrive.",
                denied_row=_DRIVES_DENIED_ROW,
                request="the OneDrive read",
            )
        return CheckOutput(
            summary=_line("Opened the OneDrive of ", _user_name(opened.user))
        )


class _DeltaCheck(_ConfigReadingCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="onedrive_delta",
            display_name="Read OneDrive changes",
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            requires_connector_config=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = _gateway(context)
        try:
            host = _config(context).graph_api_host.rstrip("/")
            opened, _ = _first_drive_that(
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
                    allow_full_resync=True,
                ),
                "The app cannot read changes in the tenant's first OneDrives.",
                _row(
                    "OneDrive changes could not be read",
                    "The OneDrives opened, but none answered the change feed in a "
                    "usable way.\nRe-run the checks.",
                ),
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot read OneDrive changes.",
                denied_row=_DRIVES_DENIED_ROW,
                request="the change feed read",
            )
        return CheckOutput(
            summary=_line("Read changes in ", _user_name(opened.user), "'s OneDrive")
        )


class _PermissionCheck(_ConfigReadingCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="onedrive_item_permissions",
            display_name="Read file permissions",
            remediation="Grant `Sites.Read.All` or a selected personal-site read grant.",
            requires_connector_config=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = _gateway(context)
        host = _config(context).graph_api_host.rstrip("/")
        try:
            _first_drive_that(
                context,
                lambda drive: _probe_item_permissions(
                    gateway, drive, f"{host}/{GRAPH_API_VERSION}"
                ),
                "The app cannot read permissions in the tenant's first OneDrives.",
                _row(
                    "No files found to test",
                    "The OneDrives the check sampled hold no file.\nAdd a file to "
                    "one of them, then run the checks again.",
                ),
            )
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot read OneDrive permissions.",
                denied_row=_DRIVES_DENIED_ROW,
                request="the permission read",
            )
        return CheckOutput(summary="Read permissions of a file in a OneDrive")


class _GroupListCheck(_OneDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_GROUPS_CHECK_ID,
            display_name="List groups",
            remediation="Grant and admin-consent `GroupMember.ReadBasic.All`.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            _gateway(context).list_groups(page_size=_PROBE_PAGE_SIZE)
        except OneDriveGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot list Entra groups.",
                denied_row=ENTRA_GROUPS_DENIED_ROW,
                request="the group listing",
            )
        return CheckOutput(summary="Entra group list is readable")


class _GroupMembershipCheck(_OneDriveCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="onedrive_group_members",
            display_name="Read group members",
            remediation="Grant `GroupMember.ReadBasic.All`.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = _gateway(context)
        denied = "The app cannot expand transitive Entra group members."
        try:
            group = _group_membership_probe_group(gateway)
            if group is None:
                raise InconclusiveValidationError(
                    "The check found no Entra group with visible membership in "
                    f"the first {_CANDIDATE_PAGES} groups, so it read no members.",
                    summary="No readable groups found",
                    description=(
                        "The first groups all hide their members, or the tenant "
                        "has none."
                    ),
                )
            gateway.list_transitive_group_members(group_id=group.id)
        except OneDriveGraphError as error:
            if error.status == 404:
                raise InconclusiveValidationError(
                    denied,
                    summary="Sample group disappeared",
                    description=(
                        "The group was deleted between the listing and the member "
                        "read.\nRe-run the checks."
                    ),
                ) from error
            raise_for_graph_error(
                error,
                denied,
                denied_row=_GROUP_MEMBERS_DENIED_ROW,
                request="the group member read",
            )
        return CheckOutput(
            summary=_line("Read members of ", group.display_name or group.id)
        )


def build_onedrive_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _UsersCheck(),
        _DriveCountCheck(),
        _ConfiguredUsersCheck(),
        _DriveCheck(),
        _DeltaCheck(),
    ]


def build_onedrive_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_PermissionCheck()]


def build_onedrive_group_sync_checks() -> list[CapabilityCheck]:
    return [_GroupListCheck(), _GroupMembershipCheck()]
