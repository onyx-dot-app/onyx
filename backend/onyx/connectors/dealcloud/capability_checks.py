from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.dealcloud.config import DealCloudConnectorConfig
from onyx.connectors.dealcloud.connector import (
    entry_types_not_found,
    indexed_entry_types,
    missing_entry_types,
)
from onyx.connectors.dealcloud.source_operations import (
    DealCloudApiError,
    DealCloudSourceOperations,
)
from onyx.connectors.exceptions import (
    InconclusiveValidationError,
    NothingToCheckError,
    UnexpectedValidationError,
)

T = TypeVar("T")

SIGN_IN_CHECK_ID: str = "dealcloud_sign_in"
# The gateway reads the site URL from the config, so no check runs without it.
REQUIRED_FIELDS: frozenset[str] = frozenset({"base_url"})
# Objects tried while looking for one with an entry to read.
_MAX_PROBE_ENTRY_TYPES: int = 5
_PROBE_HISTORY_WINDOW: timedelta = timedelta(days=1)


def gateway_from_context(
    context: CapabilityCheckContext,
) -> DealCloudSourceOperations:
    if not isinstance(context.source_operations, DealCloudSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def config_from_context(context: CapabilityCheckContext) -> DealCloudConnectorConfig:
    return form_config(context, DealCloudConnectorConfig)


def probe(action: Callable[[], T], denied: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only other failures are wrapped."""
    try:
        return action()
    except DealCloudApiError as error:
        raise UnexpectedValidationError(f"{denied} {error}") from error


class _SignInCheck(CapabilityCheck[DealCloudConnectorConfig]):
    config_class = DealCloudConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=SIGN_IN_CHECK_ID,
            display_name="DealCloud accepts the URL, client ID and API key",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            validates_binding=True,
            fails_when_unreachable=True,
            timeout_text=sign_in_timeout_text("DealCloud"),
            remediation=(
                "Check the DealCloud site URL, the client ID and the API key, "
                "and that the user's group has the API capability."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        probe(
            gateway_from_context(context).list_entry_types,
            "DealCloud did not list the site's objects.",
        )


class _EntryTypesCheck(CapabilityCheck[DealCloudConnectorConfig]):
    config_class = DealCloudConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="dealcloud_entry_types",
            display_name="Configured objects are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            depends_on=(SIGN_IN_CHECK_ID,),
            reports_field="entry_types",
            remediation=(
                "Check each object's API name, or give the API user's group "
                "access to the object."
            ),
        )

    def applies(self, form_state: FormState[DealCloudConnectorConfig]) -> bool:
        return bool(form_state.config.entry_types)

    def run(self, context: CapabilityCheckContext) -> None:
        names: list[str] = config_from_context(context).entry_types or []
        missing: list[str] = probe(
            lambda: missing_entry_types(
                gateway_from_context(context).list_entry_types(), names
            ),
            "The configured objects could not be checked.",
        )
        if missing:
            raise entry_types_not_found(missing)


class _EntriesCheck(CapabilityCheck[DealCloudConnectorConfig]):
    config_class = DealCloudConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="dealcloud_entries",
            display_name="Entries are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation="Give the API user's group Read Data for the objects.",
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: DealCloudSourceOperations = gateway_from_context(context)
        names: list[str] = config_from_context(context).entry_types or []

        def sample() -> tuple[bool, int]:
            """Whether an entry's row was read, and the number of objects in
            scope."""
            in_scope = indexed_entry_types(gateway, names)
            for entry_type in in_scope[:_MAX_PROBE_ENTRY_TYPES]:
                gateway.list_fields(entry_type_id=entry_type.id)
                gateway.list_changed_entry_ids(
                    entry_type_id=entry_type.id,
                    modified_since=datetime.now(timezone.utc) - _PROBE_HISTORY_WINDOW,
                )
                entry_ids: list[int] = gateway.list_entry_ids(
                    entry_type_id=entry_type.id
                )
                if not entry_ids:
                    continue
                if not gateway.get_rows(
                    entry_type_id=entry_type.id, entry_ids=entry_ids[:1]
                ):
                    raise UnexpectedValidationError(
                        f"DealCloud listed a {entry_type.api_name} entry but "
                        "returned no row for it."
                    )
                return True, len(in_scope)
            return False, len(in_scope)

        read, in_scope = probe(sample, "The API user cannot read entries.")
        if read:
            return
        if in_scope > _MAX_PROBE_ENTRY_TYPES:
            raise InconclusiveValidationError(
                f"The first {_MAX_PROBE_ENTRY_TYPES} objects in scope have no "
                "entry, so row access was not checked.",
                summary="No entry found to read",
            )
        raise NothingToCheckError(
            "No object in scope has an entry, so row access was not checked.",
            summary="No entries yet",
        )


def build_dealcloud_indexing_checks() -> list[CapabilityCheck]:
    return [_SignInCheck(), _EntryTypesCheck(), _EntriesCheck()]
