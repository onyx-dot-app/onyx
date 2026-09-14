"""Capability checks for the Outlook connector.

Each check composes the gateway operations the indexing path itself uses, at
the smallest page size Graph allows, so a passing check proves the exact calls
a run will make. Checks need no connector instance: the runner constructs the
registered ``OutlookSourceOperations`` gateway from the credential and hands it
to every check, so they also run at credential-creation time.

Permission-to-capability mapping (application permissions):

- ``Mail.Read``     -> INDEXING (folders, message delta, message bodies)
- ``User.Read.All`` -> INDEXING (mailbox enumeration and address resolution)

Exchange RBAC for Applications or an application access policy can narrow the
mailboxes those grants reach. A mailbox outside that scope answers 403 exactly
like a missing grant, so the remediation text names both causes.
"""

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.outlook.errors import (
    EXCHANGE_SCOPE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookGraphError,
    OutlookMailbox,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations

_OUTLOOK_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/outlook"

# Connector config key holding the explicit mailbox list. Mirrors the
# constructor argument of ``OutlookConnector``.
CONFIG_MAILBOXES = "mailboxes"

# A well-known folder every mailbox has, used to prove name resolution works.
_PROBE_WELL_KNOWN_FOLDER = "junkemail"

# One item proves the permission. More only spends the tenant's budget.
_PROBE_PAGE_SIZE = 1

# Bound the per-address probes so a report on a long list still returns.
_MAX_CONFIGURED_MAILBOXES_PROBED = 25

_LISTING_DENIED = (
    "The app cannot look up the tenant's users, which every-mailbox mode and "
    "address resolution both need. Grant the `User.Read.All` application "
    "permission and admin-consent it."
)


def _gateway(context: CapabilityCheckContext) -> OutlookSourceOperations:
    assert isinstance(context.source_operations, OutlookSourceOperations), (
        "Bug: the runner constructs the registered gateway for migrated sources."
    )
    return context.source_operations


def _configured_addresses(context: CapabilityCheckContext) -> list[str]:
    config = context.connector_specific_config or {}
    raw = config.get(CONFIG_MAILBOXES) or []
    return [str(address).strip() for address in raw if str(address).strip()]


def _resolve(gateway: OutlookSourceOperations, address: str) -> OutlookMailbox | None:
    try:
        return gateway.resolve_mailbox(address=address)
    except OutlookGraphError as e:
        raise_for_graph_error(e, _LISTING_DENIED)


def _first_mailbox(
    gateway: OutlookSourceOperations, context: CapabilityCheckContext
) -> OutlookMailbox:
    """The mailbox the read probes target: the first configured one, else the
    first enabled user in the tenant."""
    addresses = _configured_addresses(context)
    if addresses:
        address = addresses[0]
    else:
        try:
            page = gateway.list_mailbox_users(page_size=_PROBE_PAGE_SIZE)
        except OutlookGraphError as e:
            raise_for_graph_error(e, _LISTING_DENIED)
        if not page.mailboxes:
            raise UnexpectedValidationError(
                "The tenant reports no enabled users, so there is no mailbox to probe."
            )
        address = page.mailboxes[0].address
    mailbox = _resolve(gateway, address)
    if mailbox is None:
        raise ConnectorValidationError(
            f"No user matches `{address}`. {MAILBOX_UNAVAILABLE_REMEDIATION}"
        )
    return mailbox


class _TokenAuthCheck(CapabilityCheck):
    """Asks Entra for a token. A blank credential field fails here too, since
    the gateway refuses to build the MSAL app without all three."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_token_auth",
            display_name="App registration can sign in",
            requires_connector_instance=False,
            remediation=(
                "Enter the client id, directory (tenant) id and a current "
                "client secret of the Entra app registration."
            ),
            docs_link=_OUTLOOK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).check_token()
        except OutlookAuthError as e:
            raise_for_auth_error(e)


class _MailboxListingCheck(CapabilityCheck):
    """Lists one user. Proves ``User.Read.All``."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_mailbox_listing",
            display_name="Tenant users can be listed",
            requires_connector_instance=False,
            remediation=(
                "Grant the `User.Read.All` application permission to the app "
                "registration and admin-consent it."
            ),
            docs_link=_OUTLOOK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).list_mailbox_users(page_size=_PROBE_PAGE_SIZE)
        except OutlookGraphError as e:
            raise_for_graph_error(e, _LISTING_DENIED)


class _MailReadCheck(CapabilityCheck):
    """Reads folders and one delta page of one mailbox. Proves ``Mail.Read``
    and that the mailbox is inside the app's Exchange scope."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_mail_read",
            display_name="Mail in one mailbox is readable",
            requires_connector_instance=False,
            remediation=EXCHANGE_SCOPE_REMEDIATION,
            docs_link=_OUTLOOK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        mailbox = _first_mailbox(gateway, context)
        denied = f"The app cannot read mail in `{mailbox.address}`."
        try:
            inbox = gateway.probe_mailbox(mailbox_id=mailbox.id)
            gateway.get_well_known_folder(
                mailbox_id=mailbox.id, name=_PROBE_WELL_KNOWN_FOLDER
            )
            gateway.list_child_folders(
                mailbox_id=mailbox.id, page_size=_PROBE_PAGE_SIZE
            )
            gateway.fetch_folder_delta_page(
                mailbox_id=mailbox.id, folder_id=inbox.id, page_size=_PROBE_PAGE_SIZE
            )
        except OutlookGraphError as e:
            raise_for_graph_error(e, denied)


class _ConfiguredMailboxesCheck(CapabilityCheck):
    """Resolves and probes every explicitly configured mailbox.

    Skipped in every-mailbox mode, where denied mailboxes are logged and
    skipped at index time instead of blocking validation.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_configured_mailboxes",
            display_name="Configured mailboxes are reachable",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation=f"{MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}",
            docs_link=_OUTLOOK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        addresses = _configured_addresses(context)
        if not addresses:
            return
        gateway = _gateway(context)
        unresolved: list[str] = []
        unavailable: list[str] = []
        for address in addresses[:_MAX_CONFIGURED_MAILBOXES_PROBED]:
            mailbox = _resolve(gateway, address)
            if mailbox is None:
                unresolved.append(address)
                continue
            try:
                gateway.probe_mailbox(mailbox_id=mailbox.id)
            except OutlookGraphError as e:
                if e.status in (403, 404):
                    unavailable.append(f"{address} ({e.code})")
                    continue
                raise_for_graph_error(e, f"The app cannot read `{address}`.")

        problems: list[str] = []
        if unresolved:
            problems.append(f"no user matches {', '.join(unresolved)}")
        if unavailable:
            problems.append(
                "no mailbox, no license, or outside the app's Exchange scope: "
                + ", ".join(unavailable)
            )
        if problems:
            raise ConnectorValidationError(
                "Configured mailboxes cannot be indexed. "
                + ". ".join(problems)
                + f". {MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}"
            )


def build_outlook_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenAuthCheck(),
        _MailboxListingCheck(),
        _MailReadCheck(),
        _ConfiguredMailboxesCheck(),
    ]
