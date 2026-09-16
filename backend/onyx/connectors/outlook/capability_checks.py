"""Capability checks for the Outlook connector.

Each check composes the gateway operations the indexing path itself uses, at
the smallest page size Graph allows, so a passing check proves the exact calls
a run will make. Checks need no connector instance: the runner constructs the
registered ``OutlookSourceOperations`` gateway from the credential and hands it
to every check, so they also run at credential-creation time.

Permission-to-capability mapping (application permissions):

- ``Mail.Read``     -> INDEXING (folders, message delta, message bodies, attachments)
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
    MAILBOX_UNAVAILABLE_STATUSES,
    configured_addresses,
    describe_unavailable_mailboxes,
    raise_if_unavailable,
    resolve_mailbox_for_validation,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookFolder,
    OutlookGraphError,
    OutlookMailbox,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations

_OUTLOOK_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/outlook"

# A well-known folder every mailbox has, used to prove name resolution works.
_PROBE_WELL_KNOWN_FOLDER = "junkemail"

# One item proves the permission. More only spends the tenant's budget.
_PROBE_PAGE_SIZE = 1

# Every-mailbox mode reads up to this many one-user pages looking for a
# mailbox that opens. Graph may hand back empty continuation pages, so the
# bound is on pages rather than users.
_CANDIDATE_PAGES = 20

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


def _denied(mailbox: OutlookMailbox) -> str:
    return f"The app cannot read mail in `{mailbox.address}`."


def _open_configured_mailbox(
    gateway: OutlookSourceOperations, address: str
) -> tuple[OutlookMailbox, OutlookFolder]:
    """A named mailbox must open, so every failure here is final."""
    mailbox = resolve_mailbox_for_validation(gateway, address)
    if mailbox is None:
        raise ConnectorValidationError(
            f"No user matches `{address}`. {MAILBOX_UNAVAILABLE_REMEDIATION}"
        )
    try:
        return mailbox, gateway.probe_mailbox(mailbox_id=mailbox.id)
    except OutlookGraphError as e:
        raise_for_graph_error(e, _denied(mailbox))


def _open_first_readable_mailbox(
    gateway: OutlookSourceOperations,
) -> tuple[OutlookMailbox, OutlookFolder]:
    """Walk the user listing one user at a time until a mailbox opens.

    Enabled users without a mailbox, such as directory sync service accounts,
    are common and indexing skips them too, so they must not fail the check.
    A 403 is remembered: when no mailbox opens it is the likelier cause.
    """
    denied: OutlookGraphError | None = None
    next_link: str | None = None
    for _ in range(_CANDIDATE_PAGES):
        try:
            page = gateway.list_mailbox_users(
                page_size=_PROBE_PAGE_SIZE, next_link=next_link
            )
        except OutlookGraphError as e:
            raise_for_graph_error(e, USER_LISTING_DENIED)
        if page.mailboxes:
            mailbox = page.mailboxes[0]
            try:
                return mailbox, gateway.probe_mailbox(mailbox_id=mailbox.id)
            except OutlookGraphError as e:
                if e.status not in MAILBOX_UNAVAILABLE_STATUSES:
                    raise_for_graph_error(e, _denied(mailbox))
                if e.status == 403:
                    denied = e
        next_link = page.next_link
        if next_link is None:
            break
    if denied is not None:
        raise_for_graph_error(
            denied, "The app cannot read mail in the tenant's first mailboxes."
        )
    raise UnexpectedValidationError(
        "None of the tenant's first enabled users has a mailbox to probe. List a "
        "mailbox to verify it."
    )


class _TokenAuthCheck(CapabilityCheck):
    """Asks Entra for a token. A blank credential field fails here too, since
    the gateway refuses to build the MSAL app without every field its
    authentication method needs."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_token_auth",
            display_name="App registration can sign in",
            requires_connector_instance=False,
            remediation=(
                "Enter the client id, directory (tenant) id and a current "
                "client secret or certificate of the Entra app registration."
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
    """Reads folders, one delta page, one message body and, when that message
    has any, its attachment records. Proves ``Mail.Read`` and that the mailbox
    is inside the app's Exchange scope."""

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
        addresses = configured_addresses(context.connector_specific_config)
        if addresses:
            mailbox, inbox = _open_configured_mailbox(gateway, addresses[0])
        else:
            mailbox, inbox = _open_first_readable_mailbox(gateway)
        try:
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
            raise_for_graph_error(e, _denied(mailbox))

        try:
            sample = gateway.read_any_message(mailbox_id=mailbox.id)
        except OutlookGraphError as e:
            raise_for_graph_error(e, _BODY_DENIED)
        # Nothing to read means nothing proven, which is not a pass.
        if sample is None:
            raise UnexpectedValidationError(
                f"`{mailbox.address}` holds no messages, so body access could not "
                "be proven. List a mailbox that has mail to verify it."
            )
        if not sample.has_attachments:
            return
        try:
            gateway.list_message_attachments(
                mailbox_id=mailbox.id, message_id=sample.id, limit=1
            )
        except OutlookGraphError as e:
            # The sample can be deleted between the two reads. The body read
            # already proved the grant, so that is not a failure.
            if e.status == 404:
                return
            raise_for_graph_error(e, _denied(mailbox))


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
