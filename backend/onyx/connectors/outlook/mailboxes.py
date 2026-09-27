"""Which configured mailboxes the app can open.

Validation and the capability checks probe the same addresses the same way, so
the rule lives here once and neither path can drift from the other.
"""

from typing import Any

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.outlook.errors import (
    EXCHANGE_SCOPE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    USER_LISTING_DENIED,
    raise_for_graph_error,
)
from onyx.connectors.outlook.models import OutlookMailbox
from onyx.connectors.outlook.source_operations import OutlookSourceOperations

# Connector config key holding the explicit mailbox list. Empty means every
# mailbox the app may open.
CONFIG_MAILBOXES = "mailboxes"


def configured_addresses(config: dict[str, Any] | None) -> list[str]:
    raw = (config or {}).get(CONFIG_MAILBOXES) or []
    return [str(address).strip() for address in raw if str(address).strip()]


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
