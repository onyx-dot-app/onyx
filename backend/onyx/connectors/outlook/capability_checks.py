"""Capability checks for the Outlook connector.

Each check composes the gateway operations the indexing path itself uses, at
the smallest page size Graph allows, so a passing check proves the exact calls
a run will make. Checks need no connector instance: the runner constructs the
registered ``OutlookSourceOperations`` gateway from the credential and hands it
to every check, so they also run at credential-creation time.

Permission-to-capability mapping (application permissions):

- ``Mail.Read``     -> INDEXING (folders, message delta, message bodies, attachments)
- ``User.Read.All`` -> INDEXING (mailbox enumeration and address resolution) and
  DOC_PERMISSION_SYNC (the owner address every access list is built from)
- ``Calendars.Read`` -> INDEXING (calendar view and series masters, only when the
  connector indexes calendars)

Exchange RBAC for Applications or an application access policy can narrow the
mailboxes those grants reach. A mailbox outside that scope answers 403 exactly
like a missing grant, so the remediation text names both causes.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.outlook.errors import (
    CALENDAR_READ_REMEDIATION,
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
    OutlookEvent,
    OutlookEventPage,
    OutlookFolder,
    OutlookGraphError,
    OutlookMailbox,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations

T = TypeVar("T")

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


def _calendar_denied(mailbox: OutlookMailbox) -> str:
    return f"The app cannot read the calendar of `{mailbox.address}`."


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


_NO_MAILBOX_TO_PROBE = (
    "None of the tenant's first enabled users has a mailbox to probe. List a "
    "mailbox to verify it."
)


def _first_mailbox_that(
    gateway: OutlookSourceOperations,
    opens: Callable[[OutlookMailbox], T | None],
    denied_one: Callable[[OutlookMailbox], str],
    denied_all: str,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
    nothing_to_probe: str = _NO_MAILBOX_TO_PROBE,
) -> tuple[OutlookMailbox, T]:
    """Walk the user listing one user at a time until ``opens`` returns
    something on a mailbox, and return that mailbox with what it opened.
    ``opens`` returning None means the mailbox proves nothing, keep walking.

    Enabled users without a mailbox, such as directory sync service accounts,
    are common and indexing skips them too, so they must not fail the check.
    Exchange scopes are per grant, so a mailbox the app may read mail in can
    still refuse its calendar. A 403 is remembered: when nothing opens it is
    the likelier cause.
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
                opened = opens(mailbox)
            except OutlookGraphError as e:
                if not e.is_permanent_refusal:
                    raise_for_graph_error(e, denied_one(mailbox), remediation)
                if e.status == 403:
                    denied = e
            else:
                if opened is not None:
                    return mailbox, opened
        next_link = page.next_link
        if next_link is None:
            break
    if denied is not None:
        raise_for_graph_error(denied, denied_all, remediation)
    raise UnexpectedValidationError(nothing_to_probe)


def _open_first_readable_mailbox(
    gateway: OutlookSourceOperations,
) -> tuple[OutlookMailbox, OutlookFolder]:
    return _first_mailbox_that(
        gateway,
        lambda mailbox: gateway.probe_mailbox(mailbox_id=mailbox.id),
        _denied,
        "The app cannot read mail in the tenant's first mailboxes.",
    )


def _open_sample_mailbox(
    gateway: OutlookSourceOperations, config: dict[str, Any] | None
) -> tuple[OutlookMailbox, OutlookFolder]:
    """The first configured mailbox, or the first readable one when the
    connector indexes every mailbox."""
    addresses = configured_addresses(config)
    if addresses:
        return _open_configured_mailbox(gateway, addresses[0])
    return _open_first_readable_mailbox(gateway)


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

    def __init__(
        self, capability: CredentialCapability = CredentialCapability.INDEXING
    ) -> None:
        super().__init__(
            capability=capability,
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
        mailbox, inbox = _open_sample_mailbox(
            gateway, context.connector_specific_config
        )
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


_CONFIG_INCLUDE_CALENDAR = "include_calendar"

# Calendars.ReadBasic.All lists events but withholds their bodies, so the
# calendar probe must read one body to tell the two grants apart.
_EVENT_BODY_DENIED = (
    "The app can list events but not read their bodies. "
    "`Calendars.ReadBasic.All` is not enough, grant `Calendars.Read`."
)


def _event_with_body(
    gateway: OutlookSourceOperations, mailbox: OutlookMailbox
) -> OutlookEvent | None:
    """One event with its body, None for an empty calendar. A body Graph refuses
    or withholds is ``Calendars.ReadBasic.All`` at work, which another mailbox
    cannot cure, so that fails at once."""
    try:
        sample = gateway.read_any_event(mailbox_id=mailbox.id)
    except OutlookGraphError as e:
        raise_for_graph_error(e, _EVENT_BODY_DENIED, CALENDAR_READ_REMEDIATION)
    if sample is not None and not sample.body_present:
        raise InsufficientPermissionsError(
            f"{_EVENT_BODY_DENIED} {CALENDAR_READ_REMEDIATION}"
        )
    return sample


class _CalendarReadCheck(CapabilityCheck):
    """Reads one page of one mailbox's calendar view, the call indexing makes,
    then one event with its body, which ``Calendars.ReadBasic.All`` withholds.
    Together they prove ``Calendars.Read``. An empty calendar proves the
    listing only, so in every-mailbox mode the walk moves on to one with
    events. A connector that does not index calendars needs no such grant, so
    the check passes without a call for it."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="outlook_calendar_read",
            display_name="Calendar of one mailbox is readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation=CALENDAR_READ_REMEDIATION,
            docs_link=_OUTLOOK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        if not (context.connector_specific_config or {}).get(_CONFIG_INCLUDE_CALENDAR):
            return
        gateway = _gateway(context)
        now = datetime.now(timezone.utc)

        def view(mailbox: OutlookMailbox) -> OutlookEventPage:
            return gateway.fetch_calendar_delta_page(
                mailbox_id=mailbox.id,
                window_start=now - timedelta(days=1),
                window_end=now + timedelta(days=1),
                page_size=1,
            )

        def calendar_with_event(mailbox: OutlookMailbox) -> OutlookEvent | None:
            view(mailbox)
            return _event_with_body(gateway, mailbox)

        addresses = configured_addresses(context.connector_specific_config)
        if addresses:
            mailbox, _ = _open_configured_mailbox(gateway, addresses[0])
            try:
                view(mailbox)
            except OutlookGraphError as e:
                raise_for_graph_error(
                    e, _calendar_denied(mailbox), CALENDAR_READ_REMEDIATION
                )
            # Nothing to read means nothing proven, which is not a pass.
            if _event_with_body(gateway, mailbox) is None:
                raise UnexpectedValidationError(
                    f"`{mailbox.address}` holds no events, so body access could "
                    "not be proven. List a mailbox that has events to verify it."
                )
            return
        _first_mailbox_that(
            gateway,
            calendar_with_event,
            _calendar_denied,
            "The app cannot read the calendar of the tenant's first mailboxes.",
            CALENDAR_READ_REMEDIATION,
            nothing_to_probe=(
                "None of the tenant's first mailboxes holds an event to probe. "
                "List a mailbox that has events to verify it."
            ),
        )


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
        _CalendarReadCheck(),
        _ConfiguredMailboxesCheck(),
    ]


def build_outlook_doc_permission_sync_checks() -> list[CapabilityCheck]:
    """The permission walk shares indexing's mail and calendar grants, proven by
    its checks in the same run, so this capability proves only the user listing
    every owner address comes from. The runner executes a check id once and
    mirrors the outcome onto each capability that registers it."""
    return [_MailboxListingCheck(CredentialCapability.DOC_PERMISSION_SYNC)]
