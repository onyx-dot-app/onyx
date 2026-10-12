"""Which configured mailboxes the app can open.

Validation and the capability checks probe the same addresses the same way, so
the rule lives here once and neither path can drift from the other.
"""

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.outlook.config import OutlookConnectorConfig
from onyx.connectors.outlook.errors import (
    EXCHANGE_SCOPE_REMEDIATION,
    GROUP_LISTING_DENIED,
    GROUP_LISTING_REMEDIATION,
    GROUP_UNAVAILABLE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    USER_LISTING_DENIED,
    raise_for_graph_error,
)
from onyx.connectors.outlook.models import OutlookMailbox
from onyx.connectors.outlook.source_operations import OutlookSourceOperations


def clean_names(values: list[str] | None) -> list[str]:
    """The configured names stripped and without blanks."""
    return [value.strip() for value in values or [] if value.strip()]


def configured_addresses(config: OutlookConnectorConfig) -> list[str]:
    """The explicit mailbox list. Empty with no groups means every mailbox the app may open."""
    return clean_names(config.mailboxes)


def configured_groups(config: OutlookConnectorConfig) -> list[str]:
    """The configured Entra groups, by display name or object id."""
    return clean_names(config.mailbox_groups)


def resolve_mailbox_for_validation(
    gateway: OutlookSourceOperations, address: str
) -> OutlookMailbox | None:
    """Resolve an address, mapping a Graph failure onto the validation family."""
    try:
        return gateway.resolve_mailbox(address=address)
    except OutlookGraphError as e:
        raise_for_graph_error(e, USER_LISTING_DENIED)


def describe_unavailable_mailboxes(
    gateway: OutlookSourceOperations, addresses: list[str]
) -> list[str]:
    """One line per named mailbox that cannot be indexed, empty when all can.

    Raises the validation family for anything that is not about the mailbox
    itself, such as a denied user listing or a throttled call.
    """
    problems: list[str] = []
    for address in addresses:
        mailbox = resolve_mailbox_for_validation(gateway, address)
        if mailbox is None:
            problems.append(f"{address} (no such user)")
            continue
        try:
            gateway.probe_mailbox(mailbox_id=mailbox.id)
        except OutlookGraphError as e:
            if e.is_permanent_refusal:
                problems.append(f"{address} ({e.code})")
                continue
            raise_for_graph_error(e, f"The app cannot read `{address}`.")
    return problems


def raise_if_unavailable(problems: list[str]) -> None:
    if not problems:
        return
    raise ConnectorValidationError(
        "These mailboxes cannot be indexed: "
        + ", ".join(problems)
        + f". {MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}"
    )


def describe_group_mismatch(identifier: str, match_count: int) -> str:
    """Why a group identifier that does not name exactly one group is unusable."""
    if match_count == 0:
        return f"No group matches {identifier}"
    return f"More than one group is named {identifier}"


def describe_unavailable_groups(
    gateway: OutlookSourceOperations, identifiers: list[str]
) -> list[str]:
    """One line per configured group that does not name exactly one Entra
    group, empty when all do."""
    problems: list[str] = []
    for identifier in identifiers:
        try:
            match_count = len(gateway.resolve_groups(identifier=identifier))
        except OutlookGraphError as e:
            raise_for_graph_error(e, GROUP_LISTING_DENIED, GROUP_LISTING_REMEDIATION)
        if match_count != 1:
            problems.append(describe_group_mismatch(identifier, match_count))
    return problems


def raise_if_groups_unavailable(problems: list[str]) -> None:
    if not problems:
        return
    raise ConnectorValidationError(
        "These groups cannot be used: "
        + ", ".join(problems)
        + f". {GROUP_UNAVAILABLE_REMEDIATION}"
    )
