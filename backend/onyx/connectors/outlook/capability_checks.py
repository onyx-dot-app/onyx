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
    USER_LISTING_DENIED,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.outlook.mailboxes import (
    configured_addresses,
    describe_unavailable_mailboxes,
    raise_if_unavailable,
    resolve_mailbox_for_validation,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookGraphError,
    OutlookMailbox,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations

_OUTLOOK_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/outlook"

# A well-known folder every mailbox has, used to prove name resolution works.
_PROBE_WELL_KNOWN_FOLDER = "junkemail"

# One item proves the permission. More only spends the tenant's budget.
_PROBE_PAGE_SIZE = 1

# Graph may answer a delta request with an empty page and a next link, so a
# few pages are followed before the Inbox counts as empty.
_PROBE_DELTA_PAGES = 3

_TOKEN_ENDPOINT_DENIED = "Microsoft's token endpoint refused the request."

# Mail.ReadBasic.All answers every metadata call but refuses bodies, so the
# read probe must fetch one body to tell the two grants apart.
_BODY_DENIED = (
    "The app can list mail but not read message bodies. `Mail.ReadBasic.All` "
    "is not enough, grant `Mail.Read`."
)


def _gateway(context: CapabilityCheckContext) -> OutlookSourceOperations:
    assert isinstance(context.source_operations, OutlookSourceOperations), (
        "Bug: the runner constructs the registered gateway for migrated sources."
    )
    return context.source_operations


def _first_mailbox(
    gateway: OutlookSourceOperations, context: CapabilityCheckContext
) -> OutlookMailbox:
    """The mailbox the read probes target: the first configured one, else the
    first enabled user in the tenant."""
    addresses = configured_addresses(context.connector_specific_config)
    if addresses:
        address = addresses[0]
    else:
        try:
            page = gateway.list_mailbox_users(page_size=_PROBE_PAGE_SIZE)
        except OutlookGraphError as e:
            raise_for_graph_error(e, USER_LISTING_DENIED)
        if not page.mailboxes:
            raise UnexpectedValidationError(
                "The tenant reports no enabled users, so there is no mailbox to probe."
            )
        address = page.mailboxes[0].address
    mailbox = resolve_mailbox_for_validation(gateway, address)
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
        except OutlookGraphError as e:
            raise_for_graph_error(e, _TOKEN_ENDPOINT_DENIED)


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
            raise_for_graph_error(e, USER_LISTING_DENIED)


class _MailReadCheck(CapabilityCheck):
    """Reads folders, one delta page and one message body of one mailbox.
    Proves ``Mail.Read`` and that the mailbox is inside the app's Exchange
    scope."""

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
        conversation_id: str | None = None
        try:
            inbox = gateway.probe_mailbox(mailbox_id=mailbox.id)
            gateway.get_well_known_folder(
                mailbox_id=mailbox.id, name=_PROBE_WELL_KNOWN_FOLDER
            )
            gateway.list_child_folders(
                mailbox_id=mailbox.id, page_size=_PROBE_PAGE_SIZE
            )
            next_link: str | None = None
            for _ in range(_PROBE_DELTA_PAGES):
                page = gateway.fetch_folder_delta_page(
                    mailbox_id=mailbox.id,
                    folder_id=inbox.id,
                    page_size=_PROBE_PAGE_SIZE,
                    next_link=next_link,
                )
                conversation_id = next(
                    (
                        c.conversation_id
                        for c in page.changes
                        if not c.removed and c.conversation_id
                    ),
                    None,
                )
                next_link = page.next_link
                if conversation_id is not None or next_link is None:
                    break
        except OutlookGraphError as e:
            raise_for_graph_error(e, denied)

        if conversation_id is None:
            return
        try:
            gateway.fetch_conversation_messages_page(
                mailbox_id=mailbox.id,
                conversation_id=conversation_id,
                page_size=_PROBE_PAGE_SIZE,
            )
        except OutlookGraphError as e:
            raise_for_graph_error(e, _BODY_DENIED)


class _ConfiguredMailboxesCheck(CapabilityCheck):
    """Resolves and probes every explicitly configured mailbox.

    With no configured list the check passes without a call: every-mailbox
    mode logs and skips denied mailboxes at index time instead.
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
        addresses = configured_addresses(context.connector_specific_config)
        if not addresses:
            return
        raise_if_unavailable(
            describe_unavailable_mailboxes(_gateway(context), addresses)
        )


def build_outlook_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenAuthCheck(),
        _MailboxListingCheck(),
        _MailReadCheck(),
        _ConfiguredMailboxesCheck(),
    ]
