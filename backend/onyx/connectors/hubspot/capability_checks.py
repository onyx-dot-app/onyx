"""Capability checks for the HubSpot connector.

Each check probes one permission the connector relies on through the gateway
operations production uses, reading at most one item per call. Checks need no
connector instance: the runner builds the gateway from the credential, so they
run at credential creation too, over every object type until a config narrows
them. A probe with no record or note to call on passes, since there is no id
to exercise the permission with.
"""

from datetime import datetime, timezone
from typing import NoReturn

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
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
    HubSpotApiError,
    HubSpotSourceOperations,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/hubspot"
_PROBE_LIMIT = 1
_NOTE_BODY_PROPERTY = "hs_note_body"
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)
_USERS_SCOPE = "settings.users.read"
_INDEXED_TYPES_REMEDIATION = (
    "Grant the private app the read scope of every object type the connector indexes."
)


def _gateway(context: CapabilityCheckContext) -> HubSpotSourceOperations:
    gateway = context.source_operations
    if not isinstance(gateway, HubSpotSourceOperations):
        raise TypeError(f"HubSpot checks need the HubSpot gateway, got {gateway!r}")
    return gateway


def _object_types(config: HubSpotConnectorConfig) -> list[HubSpotObjectType]:
    """None means every type, as in the connector. [] means none."""
    if config.object_types is None:
        return list(HubSpotObjectType)
    return config.object_types


def _read_scope(object_type: HubSpotObjectType) -> str:
    return HUBSPOT_OBJECT_SPECS[object_type].read_scope


def _refused(error: HubSpotApiError, denied: str, scope: str | None) -> NoReturn:
    if error.status == 401:
        raise CredentialInvalidError(
            f"HubSpot rejected the access token when Onyx tried to {denied}."
        ) from error
    if error.status == 403:
        hint: str = f" Grant it the `{scope}` scope." if scope else ""
        raise InsufficientPermissionsError(
            f"The private app lacks permission to {denied}.{hint}"
        ) from error
    raise UnexpectedValidationError(f"Could not {denied}: {error}") from error


def _first_record(
    context: CapabilityCheckContext,
) -> tuple[HubSpotObjectType, HubSpotRecord] | None:
    """The first record of the first configured type that has one. A refused
    type raises, since the walk that needs a record lists every type."""
    gateway: HubSpotSourceOperations = _gateway(context)
    for object_type in _object_types(form_config(context, HubSpotConnectorConfig)):
        try:
            page: HubSpotPage[HubSpotRecord] = gateway.list_records(
                variant=object_type,
                properties=[HS_OBJECT_ID_PROPERTY],
                limit=_PROBE_LIMIT,
            )
        except HubSpotApiError as error:
            _refused(
                error,
                f"list {object_type.value} for a sample record",
                _read_scope(object_type),
            )
        if page.items:
            return object_type, page.items[0]
    logger.info("HubSpot has no records yet, so there is nothing to probe")
    return None


def _sample_for_optional_check(
    context: CapabilityCheckContext,
) -> tuple[HubSpotObjectType, HubSpotRecord] | None:
    """A refused listing is already the read check's failure, so an optional
    check reports it as indeterminate instead of a second failed row."""
    try:
        return _first_record(context)
    except ConnectorValidationError as error:
        raise UnexpectedValidationError(f"No record to probe: {error}") from error


class _TokenCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="hubspot_token",
            display_name="Access token is valid",
            requires_connector_instance=False,
            remediation="Create a private app in HubSpot and paste its access token.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).get_portal_id()
        except HubSpotApiError as error:
            _refused(error, "read the portal", None)


class _RecordsReadableCheck(CapabilityCheck[HubSpotConnectorConfig]):
    """Listing, search and batch read of one type share one scope, so one check
    probes all three, the batch read only when the listing returns a record."""

    config_class = HubSpotConnectorConfig

    def __init__(self, object_type: HubSpotObjectType) -> None:
        self._object_type: HubSpotObjectType = object_type
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=f"hubspot_{object_type.value}_readable",
            display_name=f"{object_type.value.capitalize()} can be read",
            requires_connector_instance=False,
            remediation=(
                f"Grant the private app the `{_read_scope(object_type)}` scope."
            ),
            docs_link=_DOCS_LINK,
        )

    def applies(self, form_state: FormState[HubSpotConnectorConfig]) -> bool:
        return self._object_type in _object_types(form_state.config)

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: HubSpotSourceOperations = _gateway(context)
        object_type: HubSpotObjectType = self._object_type
        try:
            page: HubSpotPage[HubSpotRecord] = gateway.list_records(
                variant=object_type,
                properties=[HS_OBJECT_ID_PROPERTY],
                limit=_PROBE_LIMIT,
            )
            gateway.search_records(
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
        except HubSpotApiError as error:
            _refused(error, f"read {object_type.value}", _read_scope(object_type))


class _AssociationsCheck(CapabilityCheck[HubSpotConnectorConfig]):
    """Documents fold in associated records, so the probe lists one record's
    links to another type. Optional, since indexing logs and skips associations
    it cannot read."""

    config_class = HubSpotConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="hubspot_associations",
            display_name="Associated records can be listed",
            requires_connector_instance=False,
            required=False,
            remediation=_INDEXED_TYPES_REMEDIATION,
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        sample: tuple[HubSpotObjectType, HubSpotRecord] | None = (
            _sample_for_optional_check(context)
        )
        if sample is None:
            return
        object_type, record = sample
        to_object_type: HubSpotObjectType = ASSOCIATED_TYPES[object_type][0]
        try:
            _gateway(context).list_associations(
                object_type=object_type,
                object_id=record.id,
                to_object_type=to_object_type.value,
                limit=_PROBE_LIMIT,
            )
        except HubSpotApiError as error:
            _refused(
                error,
                f"list the {to_object_type.value} linked to {object_type.value}",
                _read_scope(to_object_type),
            )


class _NotesCheck(CapabilityCheck[HubSpotConnectorConfig]):
    """Optional, since indexing logs and skips notes it cannot read."""

    config_class = HubSpotConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="hubspot_notes",
            display_name="Notes can be read",
            requires_connector_instance=False,
            required=False,
            remediation=_INDEXED_TYPES_REMEDIATION,
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        sample: tuple[HubSpotObjectType, HubSpotRecord] | None = (
            _sample_for_optional_check(context)
        )
        if sample is None:
            return
        object_type, record = sample
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            notes: HubSpotPage[str] = gateway.list_associations(
                object_type=object_type,
                object_id=record.id,
                to_object_type=NOTES_OBJECT_TYPE,
                limit=_PROBE_LIMIT,
            )
            if not notes.items:
                logger.info("The sample HubSpot record has no notes to probe")
                return
            gateway.read_records(
                variant=NOTES_OBJECT_TYPE,
                ids=notes.items,
                properties=[_NOTE_BODY_PROPERTY],
            )
        except HubSpotApiError as error:
            _refused(error, "read notes", None)


class _UsersCheck(CapabilityCheck):
    """Viewers are user ids, so the sync maps them to emails through the user
    listing and, for ids it leaves out, one user at a time."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="hubspot_users",
            display_name="Users can be listed",
            requires_connector_instance=False,
            remediation=f"Grant the private app the `{_USERS_SCOPE}` scope.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            page: HubSpotPage[HubSpotUser] = gateway.list_users(limit=_PROBE_LIMIT)
            if page.items:
                gateway.get_user(user_id=page.items[0].id)
        except HubSpotApiError as error:
            _refused(error, "list users", _USERS_SCOPE)


class _RecordViewersCheck(CapabilityCheck[HubSpotConnectorConfig]):
    config_class = HubSpotConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="hubspot_record_viewers",
            display_name="Record viewers can be read",
            requires_connector_instance=False,
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        sample: tuple[HubSpotObjectType, HubSpotRecord] | None = _first_record(context)
        if sample is None:
            return
        object_type, record = sample
        gateway: HubSpotSourceOperations = _gateway(context)
        try:
            portal_id: str = gateway.get_portal_id()
        except HubSpotApiError as error:
            _refused(error, "read the portal", None)
        try:
            gateway.get_record_viewers(
                portal_id=portal_id,
                object_type=object_type,
                record_ids=[record.id],
            )
        except HubSpotApiError as error:
            _refused(error, "read a record's viewers", None)


def build_hubspot_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        *(_RecordsReadableCheck(object_type) for object_type in HubSpotObjectType),
        _AssociationsCheck(),
        _NotesCheck(),
    ]


def build_hubspot_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_UsersCheck(), _RecordViewersCheck()]
