"""Capability checks for the HubSpot connector.

Each check probes one permission the connector relies on through the gateway
operations production uses, reading at most one page per call. Checks need no
connector instance: the runner builds the gateway from the credential, so they
run at credential creation too, over every object type until a config narrows
them.

The credential is a private app access token, so every denial names the
private app scope that HubSpot needs. A check with no record or note to probe
says so: a full read that finds nothing is SKIPPED, a sample that finds
nothing is INCOMPLETE. When no selected type has a record, the connector would
index nothing, so the first type's read check FAILS.
"""

from datetime import datetime, timezone
from typing import NoReturn

from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
    CheckRowText,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    TimedOutValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.hubspot.config import (
    HUBSPOT_OBJECT_SPECS,
    HubSpotConnectorConfig,
    HubSpotObjectType,
)
from onyx.connectors.hubspot.connector import ASSOCIATED_TYPES, HS_OBJECT_ID_PROPERTY
from onyx.connectors.hubspot.models import HubSpotPage, HubSpotRecord, HubSpotUser
from onyx.connectors.hubspot.source_operations import (
    NOTES_OBJECT_TYPE,
    USERS_PAGE_SIZE,
    HubSpotApiError,
    HubSpotConnectionError,
    HubSpotSourceOperations,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import SourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/hubspot"
_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description=(
        "The check stopped after {time_limit} without an answer from HubSpot.\n"
        "Re-run the checks."
    ),
)
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("HubSpot")
_PROBE_LIMIT = 1
_NOTE_BODY_PROPERTY = "hs_note_body"
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)
_USERS_SCOPE = "settings.users.read"
_INDEXED_TYPES_REMEDIATION = (
    "Grant the private app the read scope of every object type the connector indexes."
)
_TOKEN_CHECK_ID = "hubspot_token"
_USERS_CHECK_ID = "hubspot_users"
# What the gateway raises for a call HubSpot refused or never answered.
_GATEWAY_ERRORS = (
    HubSpotApiError,
    HubSpotConnectionError,
    RateLimitTriedTooManyTimesError,
)


def _read_check_id(object_type: HubSpotObjectType) -> str:
    return f"hubspot_{object_type.value}_readable"


# check_id to the checks it runs after. The linked-record and notes checks run
# after the sign-in only: they sample any readable type, so an empty or denied
# type does not stop them.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    **{
        _read_check_id(object_type): (_TOKEN_CHECK_ID,)
        for object_type in HubSpotObjectType
    },
    "hubspot_associations": (_TOKEN_CHECK_ID,),
    "hubspot_notes": (_TOKEN_CHECK_ID,),
    _USERS_CHECK_ID: (_TOKEN_CHECK_ID,),
    "hubspot_record_viewers": (_USERS_CHECK_ID,),
}


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _gateway(context: CapabilityCheckContext) -> HubSpotSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, HubSpotSourceOperations):
        raise TypeError(f"HubSpot checks need the HubSpot gateway, got {gateway!r}")
    return gateway


def _object_types(config: HubSpotConnectorConfig) -> list[HubSpotObjectType]:
    """The selected types in registration order. None means every type, as in
    the connector. [] means none."""
    if config.object_types is None:
        return list(HubSpotObjectType)
    return [
        object_type
        for object_type in HubSpotObjectType
        if object_type in config.object_types
    ]


def _read_scope(object_type: HubSpotObjectType) -> str:
    return HUBSPOT_OBJECT_SPECS[object_type].read_scope


def _noun(object_type: HubSpotObjectType) -> str:
    return HUBSPOT_OBJECT_SPECS[object_type].document_noun


def _counted(count: int | str, noun: str, plural: str) -> str:
    """``count`` with its noun: "1 ticket", "3 tickets", "100+ users"."""
    return f"{count} {noun if str(count) == '1' else plural}"


def _need(scope: str) -> str:
    """The line that says what the private app needs."""
    return f"In HubSpot, add `{scope}` to the private app's scopes."


_REJECTED_ROW = _RowText(
    summary="HubSpot rejected the API token",
    description=(
        "HubSpot does not accept this token. (HTTP 401)\nIn HubSpot, open the "
        "private app and copy its access token."
    ),
)
_UNREACHABLE_ROW = _RowText(
    summary="Cannot reach HubSpot",
    description=(
        "The request to HubSpot failed.\nCheck that the server can reach "
        "api.hubapi.com."
    ),
)
_REQUEST_TIMEOUT_ROW = _RowText(
    summary="Timed out",
    description="HubSpot did not answer the request in time.\nRe-run the checks.",
)
_UNEXPECTED_ROW = _RowText(
    summary="Unexpected response from HubSpot",
    description=(
        "HubSpot answered in a way that this check does not know.\nRe-run the checks."
    ),
)


def _raise_for_error(
    error: Exception,
    *,
    denied: str,
    scope: str | None = None,
    denied_row: _RowText | None = None,
) -> NoReturn:
    """Maps a gateway error onto the validation-exception family. ``denied``
    explains a 403 for this probe; ``denied_row`` is what its row shows."""
    if isinstance(error, RateLimitTriedTooManyTimesError):
        raise RateLimitedValidationError(
            "HubSpot rate limited the check past the retries. Run the checks "
            "again later.",
            summary="Rate limited by HubSpot",
            description=(
                "HubSpot kept refusing requests after 5 retries. (HTTP 429)\nWait "
                "a minute, then re-run."
            ),
        ) from error
    if isinstance(error, HubSpotConnectionError) and error.timed_out:
        raise TimedOutValidationError(
            f"HubSpot did not answer in time: {error}",
            summary=_REQUEST_TIMEOUT_ROW.summary,
            description=_REQUEST_TIMEOUT_ROW.description,
        ) from error
    if isinstance(error, HubSpotConnectionError):
        raise UnreachableValidationError(
            f"Onyx cannot connect to HubSpot: {error}",
            summary=_UNREACHABLE_ROW.summary,
            description=_UNREACHABLE_ROW.description,
        ) from error
    if not isinstance(error, HubSpotApiError):
        raise error
    status: int | None = error.status_code
    if status == 401:
        raise CredentialInvalidError(
            f"HubSpot rejected the access token when Onyx tried to {denied}.",
            summary=_REJECTED_ROW.summary,
            description=_REJECTED_ROW.description,
        ) from error
    if status == 403:
        hint: str = f" Grant it the `{scope}` scope." if scope else ""
        raise InsufficientPermissionsError(
            f"The private app lacks permission to {denied}.{hint}",
            summary=denied_row.summary if denied_row else None,
            description=denied_row.description if denied_row else None,
        ) from error
    if status in (404, 422):
        raise ConnectorValidationError(
            f"HubSpot refused the request to {denied}: {error}",
            summary="HubSpot rejected the request",
            description=(
                f"HubSpot refused the request as sent. (HTTP {status})\nRe-run "
                "the checks. If it repeats, share the error details with support."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"Could not {denied}: {error}",
        summary=_UNEXPECTED_ROW.summary,
        description=_UNEXPECTED_ROW.description,
    ) from error


def _list_one(
    gateway: HubSpotSourceOperations, object_type: HubSpotObjectType
) -> HubSpotPage[HubSpotRecord]:
    return gateway.list_records(
        variant=object_type, properties=[HS_OBJECT_ID_PROPERTY], limit=_PROBE_LIMIT
    )


def _no_records_error() -> NothingToCheckError:
    return NothingToCheckError(
        "HubSpot has no record of the selected types, so there is nothing to probe.",
        summary="No records in scope",
        description="HubSpot has no record of the selected types.",
    )


# A sample record and its type.
_Sample = tuple[HubSpotObjectType, HubSpotRecord]


def _first_readable_record(context: CapabilityCheckContext) -> _Sample:
    """The first record of the first selected type that lists one. A denied
    type is left out: its read check reports it."""
    gateway: HubSpotSourceOperations = _gateway(context)
    denied: list[HubSpotObjectType] = []
    for object_type in _object_types(form_config(context, HubSpotConnectorConfig)):
        try:
            page: HubSpotPage[HubSpotRecord] = _list_one(gateway, object_type)
        except HubSpotApiError as error:
            if error.status_code != 403:
                _raise_for_error(
                    error, denied=f"list {object_type.value} for a sample record"
                )
            logger.info("HubSpot denied %s, so the sample leaves it out", object_type)
            denied.append(object_type)
            continue
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error, denied=f"list {object_type.value} for a sample record"
            )
        if page.items:
            return object_type, page.items[0]
    if denied:
        names: str = ", ".join(object_type.value for object_type in denied)
        raise InconclusiveValidationError(
            f"No readable type has a record, and HubSpot denied {names}, so Onyx "
            "has no record to probe.",
            summary="No readable records to test",
            description=(
                f"The readable types have no records, and HubSpot denied {names}."
                "\nSee the Read rows."
            ),
        )
    raise _no_records_error()


class _HubSpotCheck(CapabilityCheck[HubSpotConnectorConfig]):
    config_class = HubSpotConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        required: bool = True,
        remediation: str | None = None,
        fails_when_unreachable: bool = False,
        timeout_text: CheckRowText = _TIMEOUT_TEXT,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            required=required,
            requires_connector_instance=False,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=timeout_text,
        )


class _TokenCheck(_HubSpotCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_TOKEN_CHECK_ID,
            display_name="Sign in to HubSpot",
            remediation="Create a private app in HubSpot and paste its access token.",
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            portal_id: str = _gateway(context).get_portal_id()
        except ConnectorMissingCredentialError as error:
            raise CredentialInvalidError(
                "The credential has no HubSpot access token.",
                summary="Account has no API token",
                description=(
                    "The account has no HubSpot token.\nPaste the private app's "
                    "access token into the API Token field of the account."
                ),
            ) from error
        except HubSpotConnectionError as error:
            if not error.timed_out:
                _raise_for_error(error, denied="read the portal")
            raise TimedOutValidationError(
                f"HubSpot did not answer the sign-in in time: {error}",
                summary=_SIGN_IN_TIMEOUT_TEXT.summary,
                description=_SIGN_IN_TIMEOUT_TEXT.description,
            ) from error
        except ValueError as error:
            # A body that is not HubSpot's portal info, e.g. a proxy page.
            raise UnexpectedValidationError(
                f"HubSpot's answer to the sign-in is not portal info: {error}",
                summary=_UNEXPECTED_ROW.summary,
                description=_UNEXPECTED_ROW.description,
            ) from error
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied="read the portal",
                denied_row=_RowText(
                    summary="Token cannot read the account",
                    description=(
                        "HubSpot refused to name the account. (HTTP 403)\nIn "
                        "HubSpot, check that the private app is active, then copy "
                        "its access token again."
                    ),
                ),
            )
        return CheckOutput(summary=f"Signed in to account {portal_id}")


def _all_selected_types_empty(
    context: CapabilityCheckContext, object_type: HubSpotObjectType
) -> bool:
    """True when every other selected type lists no record either. A type
    that cannot be listed may have records, so it is not empty."""
    gateway: HubSpotSourceOperations = _gateway(context)
    for other in _object_types(form_config(context, HubSpotConnectorConfig)):
        if other == object_type:
            continue
        try:
            if _list_one(gateway, other).items:
                return False
        except RateLimitTriedTooManyTimesError as error:
            _raise_for_error(error, denied=f"list {other.value}")
        except _GATEWAY_ERRORS:
            logger.debug("Cannot list HubSpot %s, so it may have records", other)
            return False
    return True


class _RecordsReadableCheck(_HubSpotCheck):
    """Listing, search and batch read of one type share one scope, so one check
    probes all three, the batch read only when the listing returns a record."""

    def __init__(self, object_type: HubSpotObjectType) -> None:
        self._object_type: HubSpotObjectType = object_type
        super().__init__(
            check_id=_read_check_id(object_type),
            display_name=f"Read {object_type.value}",
            remediation=(
                f"Grant the private app the `{_read_scope(object_type)}` scope."
            ),
        )

    def applies(self, form_state: FormState[HubSpotConnectorConfig]) -> bool:
        return self._object_type in _object_types(form_state.config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: HubSpotSourceOperations = _gateway(context)
        object_type: HubSpotObjectType = self._object_type
        scope: str = _read_scope(object_type)
        try:
            page: HubSpotPage[HubSpotRecord] = _list_one(gateway, object_type)
            search: HubSpotPage[HubSpotRecord] = gateway.search_records(
                variant=object_type,
                properties=[HS_OBJECT_ID_PROPERTY],
                modified_after=_EPOCH,
                modified_before=None,
                limit=_PROBE_LIMIT,
            )
            if page.items:
                gateway.read_records(
                    variant=object_type.value,
                    ids=[page.items[0].id],
                    properties=[HS_OBJECT_ID_PROPERTY],
                )
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied=f"read {object_type.value}",
                scope=scope,
                denied_row=_RowText(
                    summary=f"Token cannot read {object_type.value}",
                    description=(
                        f"Indexing cannot list or search {object_type.value}. "
                        f"(HTTP 403)\n{_need(scope)}"
                    ),
                ),
            )
        if not page.items:
            self._raise_empty(context)
        if search.total is None:
            return CheckOutput(summary=f"Read {object_type.value}")
        return CheckOutput(
            summary=(
                f"Found {_counted(search.total, _noun(object_type), object_type.value)}"
            )
        )

    def _raise_empty(self, context: CapabilityCheckContext) -> NoReturn:
        object_type: HubSpotObjectType = self._object_type
        selected: list[HubSpotObjectType] = _object_types(
            form_config(context, HubSpotConnectorConfig)
        )
        # An empty scope fails the first check that reads it: the connector
        # would index nothing.
        if selected[0] == object_type and _all_selected_types_empty(
            context, object_type
        ):
            raise ConnectorValidationError(
                "HubSpot has no record of any selected object type, so the "
                "connector would index nothing.",
                summary="No records in the selected types",
                description=(
                    "HubSpot has no record of any selected type, so indexing "
                    "would find nothing.\nAdd records in HubSpot, or check the "
                    "selected object types."
                ),
            )
        raise NothingToCheckError(
            f"HubSpot has no {object_type.value}, so Onyx could not read one.",
            summary=f"No {object_type.value} in HubSpot",
            description=(
                f"Listing and search work, and HubSpot has no {object_type.value}."
            ),
        )


class _AssociationsCheck(_HubSpotCheck):
    """Documents fold in associated records, so the probe lists one record's
    links to another type. Optional, since indexing logs and skips associations
    it cannot read."""

    def __init__(self) -> None:
        super().__init__(
            check_id="hubspot_associations",
            display_name="List linked records",
            required=False,
            remediation=_INDEXED_TYPES_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        object_type, record = _first_readable_record(context)
        to_object_type: HubSpotObjectType = ASSOCIATED_TYPES[object_type][0]
        to_scope: str = _read_scope(to_object_type)
        try:
            _gateway(context).list_associations(
                object_type=object_type,
                object_id=record.id,
                to_object_type=to_object_type.value,
                limit=_PROBE_LIMIT,
            )
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied=(
                    f"list the {to_object_type.value} linked to {object_type.value}"
                ),
                scope=to_scope,
                denied_row=_RowText(
                    summary=f"Cannot read linked {to_object_type.value}",
                    description=(
                        "Documents would index without their linked records. "
                        f"(HTTP 403)\n{_need(to_scope)}"
                    ),
                ),
            )
        return CheckOutput(
            summary=f"Listed {to_object_type.value} linked to {object_type.value}"
        )


class _NotesCheck(_HubSpotCheck):
    """Optional, since indexing logs and skips notes it cannot read."""

    def __init__(self) -> None:
        super().__init__(
            check_id="hubspot_notes",
            display_name="Sample notes",
            required=False,
            remediation=_INDEXED_TYPES_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        object_type, record = _first_readable_record(context)
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            notes: HubSpotPage[str] = gateway.list_associations(
                object_type=object_type,
                object_id=record.id,
                to_object_type=NOTES_OBJECT_TYPE,
                limit=_PROBE_LIMIT,
            )
            if notes.items:
                gateway.read_records(
                    variant=NOTES_OBJECT_TYPE,
                    ids=notes.items,
                    properties=[_NOTE_BODY_PROPERTY],
                )
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied="read notes",
                denied_row=_RowText(
                    summary="Token cannot read notes",
                    description=(
                        "Record documents would index without their notes. (HTTP "
                        "403)\nGrant the private app the read scope of each "
                        "selected object type."
                    ),
                ),
            )
        if not notes.items:
            raise InconclusiveValidationError(
                f"The sample HubSpot {_noun(object_type)} has no notes, so Onyx "
                "could not read one.",
                summary="No notes found to test",
                description="The sample record has no notes.",
            )
        return CheckOutput(summary=f"Read a note linked to a {_noun(object_type)}")


class _UsersCheck(_HubSpotCheck):
    """Viewers are user ids, so the sync maps them to emails through the user
    listing and, for ids it leaves out, one user at a time."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=_USERS_CHECK_ID,
            display_name="List users",
            remediation=f"Grant the private app the `{_USERS_SCOPE}` scope.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            page: HubSpotPage[HubSpotUser] = gateway.list_users(limit=USERS_PAGE_SIZE)
            if page.items:
                gateway.get_user(user_id=page.items[0].id)
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied="list users",
                scope=_USERS_SCOPE,
                denied_row=_RowText(
                    summary="Token cannot list users",
                    description=(
                        "Permission sync cannot turn viewer IDs into emails. (HTTP "
                        f"403)\n{_need(_USERS_SCOPE)}"
                    ),
                ),
            )
        if not page.items:
            raise InconclusiveValidationError(
                "HubSpot listed no users, so Onyx could not read one.",
                summary="No users found to test",
                description="HubSpot listed no users of the account.",
            )
        count: int | str = (
            f"{len(page.items)}+" if page.next_after is not None else len(page.items)
        )
        return CheckOutput(summary=f"{_counted(count, 'user', 'users')} found")


class _RecordViewersCheck(_HubSpotCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="hubspot_record_viewers",
            display_name="Read record viewers",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        object_type, record = self._sample(context)
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            portal_id: str = gateway.get_portal_id()
            viewers: dict[str, set[int]] = gateway.get_record_viewers(
                portal_id=portal_id,
                object_type=object_type,
                record_ids=[record.id],
            )
        except _GATEWAY_ERRORS as error:
            _raise_for_error(
                error,
                denied="read a record's viewers",
                denied_row=_RowText(
                    summary="Token cannot read record viewers",
                    description=(
                        "Permission sync cannot learn who may view each record. "
                        "(HTTP 403)"
                    ),
                ),
            )
        count: int = len(viewers.get(record.id, set()))
        return CheckOutput(
            summary=(
                f"{_counted(count, 'user', 'users')} can view a sample "
                f"{_noun(object_type)}"
            )
        )

    def _sample(self, context: CapabilityCheckContext) -> _Sample:
        """Permission sync reads every selected type, so a denied listing
        fails here too."""
        gateway: HubSpotSourceOperations = _gateway(context)
        for object_type in _object_types(form_config(context, HubSpotConnectorConfig)):
            scope: str = _read_scope(object_type)
            try:
                page: HubSpotPage[HubSpotRecord] = _list_one(gateway, object_type)
            except _GATEWAY_ERRORS as error:
                _raise_for_error(
                    error,
                    denied=f"list {object_type.value} for a sample record",
                    scope=scope,
                    denied_row=_RowText(
                        summary=f"Token cannot read {object_type.value}",
                        description=(
                            f"Permission sync cannot sync {object_type.value}. "
                            f"(HTTP 403)\n{_need(scope)}"
                        ),
                    ),
                )
            if page.items:
                return object_type, page.items[0]
        raise _no_records_error()


def build_hubspot_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        *(_RecordsReadableCheck(object_type) for object_type in HubSpotObjectType),
        _AssociationsCheck(),
        _NotesCheck(),
    ]


def build_hubspot_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_UsersCheck(), _RecordViewersCheck()]
