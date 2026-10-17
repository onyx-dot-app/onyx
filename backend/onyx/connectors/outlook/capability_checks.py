"""Capability checks for the Outlook connector.

Each check composes the gateway operations the indexing path itself uses, at
the smallest page size Graph allows, so a passing check proves the exact calls
a run will make. Checks need no connector instance: the runner constructs the
registered ``OutlookSourceOperations`` gateway from the credential and hands it
to every check, so they also run at credential-creation time.

Permission-to-capability mapping (application permissions):

- ``Mail.Read``     -> INDEXING (folders, message delta, message bodies, attachments)
- ``GroupMember.Read.All`` -> INDEXING (group resolution and member listing, when
  mailboxes are chosen by group)
- ``User.Read.All`` -> INDEXING (mailbox enumeration and address resolution) and
  DOC_PERMISSION_SYNC (the owner address every access list is built from)
- ``Calendars.Read`` -> INDEXING (calendar view and series masters, only when the
  connector indexes calendars)

Exchange RBAC for Applications or an application access policy can narrow the
mailboxes those grants reach. A mailbox outside that scope answers 403 exactly
like a missing grant, so the remediation text names both causes.

"Find selected mailboxes" and "Find selected groups" are partial finds: when
some are missing they are INCOMPLETE, and the samples after them open the
mailboxes that answer. A sampled mailbox the admin did not name stays unnamed
in the rows.
"""

from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
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
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
    ValidationError,
)
from onyx.connectors.microsoft_utils.check_text import (
    grant_line,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftRowText,
    MicrosoftSignIn,
)
from onyx.connectors.microsoft_utils.sign_in import sign_in
from onyx.connectors.outlook.config import OutlookConnectorConfig
from onyx.connectors.outlook.errors import (
    CALENDAR_READ_REMEDIATION,
    EXCHANGE_SCOPE_REMEDIATION,
    GROUP_LISTING_DENIED,
    GROUP_LISTING_REMEDIATION,
    GROUP_UNAVAILABLE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    USER_LISTING_DENIED,
    raise_for_graph_error,
)
from onyx.connectors.outlook.mailboxes import (
    GroupProblem,
    MailboxProblem,
    configured_addresses,
    configured_groups,
    describe_group_mismatch,
    describe_unavailable_groups,
    describe_unavailable_mailboxes,
    resolve_mailbox_for_validation,
)
from onyx.connectors.outlook.models import (
    OutlookEvent,
    OutlookEventPage,
    OutlookFolder,
    OutlookMailbox,
    OutlookMailboxPage,
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

# A bound on the pages the mailbox count reads. Pages hold up to 999 users, so
# the count reaches its cap long before this unless Graph sends empty pages.
_COUNT_PAGES = 20
# The longest row line the card shows.
_MAX_LINE = 40
_LOCKED_STATUS = 423
_SAMPLED_MAILBOX = "a sampled mailbox"

# Mail.ReadBasic.All answers every metadata call but refuses bodies, so the
# read probe must fetch one body to tell the two grants apart.
_BODY_DENIED = (
    "The app can list mail but not read message bodies. `Mail.ReadBasic.All` "
    "is not enough, grant `Mail.Read`."
)
# Calendars.ReadBasic.All lists events but withholds their bodies, so the
# calendar probe must read one body to tell the two grants apart.
_EVENT_BODY_DENIED = (
    "The app can list events but not read their bodies. "
    "`Calendars.ReadBasic.All` is not enough, grant `Calendars.Read`."
)

_ACCOUNT_LABELS = MicrosoftAccountLabels.with_prefix("Microsoft Outlook")
_MAIL_GRANT = grant_line("Mail.Read").replace(" to the app registration", "")
_CALENDAR_GRANT = grant_line("Calendars.Read").replace(" to the app registration", "")
_RETRY_LINE = "Re-run the checks. If it repeats, send the error details to support."

_SIGN_IN_CHECK_ID = "outlook_token_auth"
_LISTING_CHECK_ID = "outlook_mailbox_listing"
_CONFIGURED_MAILBOXES_CHECK_ID = "outlook_configured_mailboxes"
_CONFIGURED_GROUPS_CHECK_ID = "outlook_configured_groups"
# Not the selected mailboxes and groups: those need a config, and a
# config-less run still samples a tenant mailbox.
_SAMPLE_DEPENDS_ON: tuple[str, ...] = (_LISTING_CHECK_ID,)
# check_id to the checks it runs after, in run order.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _LISTING_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    "outlook_mailbox_count": (_SIGN_IN_CHECK_ID,),
    _CONFIGURED_MAILBOXES_CHECK_ID: (_LISTING_CHECK_ID,),
    _CONFIGURED_GROUPS_CHECK_ID: (_LISTING_CHECK_ID,),
    "outlook_mail_read": _SAMPLE_DEPENDS_ON,
    "outlook_calendar_read": _SAMPLE_DEPENDS_ON,
}


def _line(prefix: str, name: str, suffix: str = "") -> str:
    """``prefix``, ``name`` and ``suffix``, with the name cut to fit the row."""
    room: int = _MAX_LINE - len(prefix) - len(suffix)
    cut: str = name if len(name) <= room else name[: room - 1] + "…"
    return f"{prefix}{cut}{suffix}"


def _row(summary: str, description: str) -> MicrosoftRowText:
    return MicrosoftRowText(summary=summary, description=description)


def _raise_row(
    error_class: type[ValidationError], message: str, row: MicrosoftRowText
) -> NoReturn:
    raise error_class(message, summary=row.summary, description=row.description)


_USERS_DENIED_ROW = _row(
    "No permission to read user directory",
    "Every-mailbox mode and address lookups would not work.\nGrant "
    "`User.Read.All` and admin-consent it.",
)
_GROUPS_DENIED_ROW = _row(
    "No permission to read Entra groups",
    "The app cannot read groups.\n" + grant_line("GroupMember.Read.All"),
)
_NO_MAILBOX_ROW = _row(
    "No mailboxes found to test",
    "None of the sampled users has a mailbox the app could open.\nAdd a mailbox "
    "to Mailboxes, then run the checks again.",
)
_MESSAGES_UNENDING_ROW = _row(
    "Message listing did not finish",
    "Microsoft kept returning empty pages.\nRe-run the checks later.",
)
_EVENTS_UNENDING_ROW = _row(
    "Event listing did not finish",
    "Microsoft kept returning empty pages.\nRe-run the checks later.",
)


def _gateway(context: CapabilityCheckContext) -> OutlookSourceOperations:
    if not isinstance(context.source_operations, OutlookSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def _denied(mailbox: OutlookMailbox) -> str:
    return f"The app cannot read mail in `{mailbox.address}`."


def _calendar_denied(mailbox: OutlookMailbox) -> str:
    return f"The app cannot read the calendar of `{mailbox.address}`."


def _mail_denied_row(name: str) -> MicrosoftRowText:
    return _row(
        _line("No permission to read mail in ", name),
        f"The app cannot open this mailbox.\n{_MAIL_GRANT}",
    )


def _unusable_mailbox_row(name: str) -> MicrosoftRowText:
    return _row(
        _line("No usable mailbox for ", name),
        "The user exists but has no mailbox the app can open: no Exchange "
        "license, or the mailbox is locked or archived.",
    )


def _mailbox_not_found_row(address: str) -> MicrosoftRowText:
    return _row(
        _line("Mailbox not found: ", address),
        "No user has this address.\nUse the user principal name or primary SMTP "
        "address in Mailboxes.",
    )


def _raise_for_mailbox_error(
    error: OutlookGraphError,
    mailbox: OutlookMailbox,
    name: str,
    *,
    message: str | None = None,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
    denied_row: MicrosoftRowText | None = None,
    unending_row: MicrosoftRowText | None = None,
    request: str = "the mailbox read",
) -> NoReturn:
    raise_for_graph_error(
        error,
        message or _denied(mailbox),
        remediation,
        denied_row=denied_row or _mail_denied_row(name),
        not_found_row=_unusable_mailbox_row(name),
        empty_pages_row=unending_row,
        request=request,
    )


class _Sample(BaseModel):
    """A mailbox that opened, and the name its rows give it: the address an
    admin typed, else "a sampled mailbox". Built from the gateway's models
    without validating them again."""

    mailbox: OutlookMailbox
    inbox: OutlookFolder
    name: str


def _open_configured_mailbox(
    gateway: OutlookSourceOperations, addresses: list[str]
) -> _Sample:
    """The first named mailbox that opens. A missing or unusable one is
    skipped: "Find selected mailboxes" reports it. None opening FAILS with
    the first one's row."""
    denied: tuple[OutlookGraphError, OutlookMailbox] | None = None
    unusable: tuple[OutlookGraphError, OutlookMailbox] | None = None
    for address in addresses:
        mailbox = resolve_mailbox_for_validation(gateway, address)
        if mailbox is None:
            continue
        try:
            return _Sample.model_construct(
                mailbox=mailbox,
                inbox=gateway.probe_mailbox(mailbox_id=mailbox.id),
                name=address,
            )
        except OutlookGraphError as e:
            if not e.is_permanent_refusal:
                _raise_for_mailbox_error(e, mailbox, address)
            if e.status == 403:
                denied = denied or (e, mailbox)
            else:
                unusable = unusable or (e, mailbox)
    refused: tuple[OutlookGraphError, OutlookMailbox] | None = denied or unusable
    if refused is not None:
        error, mailbox = refused
        _raise_for_mailbox_error(error, mailbox, mailbox.address)
    _raise_row(
        ConnectorValidationError,
        f"No user matches `{addresses[0]}`. {MAILBOX_UNAVAILABLE_REMEDIATION}",
        _mailbox_not_found_row(addresses[0]),
    )


class _Candidates:
    """The mailboxes the checks may probe, as pages: the members of every
    configured group, or the tenant's users when no group is configured. The
    checks must not read a mailbox outside the configured scope."""

    def __init__(
        self, gateway: OutlookSourceOperations, config: OutlookConnectorConfig
    ) -> None:
        self._gateway = gateway
        self._group_names: list[str] = configured_groups(config)

    @property
    def from_groups(self) -> bool:
        return bool(self._group_names)

    def _group_ids(self) -> list[str]:
        """The configured groups that name exactly one Entra group. Others
        are skipped: "Find selected groups" reports them. None usable FAILS
        with the first one's row."""
        group_ids: list[str] = []
        for name in self._group_names:
            matches: list[EntraGroup] = self._gateway.resolve_groups(identifier=name)
            if len(matches) == 1:
                group_ids.append(matches[0].id)
        if group_ids:
            return group_ids
        first: str = self._group_names[0]
        _raise_row(
            ConnectorValidationError,
            f"{describe_group_mismatch(first, 0)}. {GROUP_UNAVAILABLE_REMEDIATION}",
            _row(
                _line("Group not found: ", first),
                "A Mailbox Groups entry does not name exactly one Entra group.\n"
                "Use the group's object ID in Mailbox Groups.",
            ),
        )

    def pages(self) -> Generator[OutlookMailboxPage, None, None]:
        """At most _CANDIDATE_PAGES pages in all, so a huge scope stays bounded."""
        budget = _CANDIDATE_PAGES
        if not self.from_groups:
            next_link: str | None = None
            while budget > 0:
                budget -= 1
                page = self._gateway.list_mailbox_users(
                    page_size=_PROBE_PAGE_SIZE, next_link=next_link
                )
                yield page
                next_link = page.next_link
                if next_link is None:
                    return
            return
        for group_id in self._group_ids():
            next_link = None
            while budget > 0:
                budget -= 1
                page = self._gateway.list_group_mailbox_users(
                    group_id=group_id, page_size=_PROBE_PAGE_SIZE, next_link=next_link
                )
                yield page
                next_link = page.next_link
                if next_link is None:
                    break


def _first_mailbox_that(
    candidates: _Candidates,
    opens: Callable[[OutlookMailbox], T | None],
    denied_one: Callable[[OutlookMailbox], str],
    denied_all: str,
    *,
    denied_all_row: MicrosoftRowText,
    nothing_to_probe: MicrosoftRowText,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
    unending_row: MicrosoftRowText | None = None,
) -> tuple[OutlookMailbox, T]:
    """Walk the candidates one user at a time until ``opens`` returns
    something on a mailbox, and return that mailbox with what it opened.
    ``opens`` returning None means the mailbox proves nothing, keep walking.

    Enabled users without a mailbox, such as directory sync service accounts,
    are common and indexing skips them too, so they must not fail the check.
    Exchange scopes are per grant, so a mailbox the app may read mail in can
    still refuse its calendar. A 403 is remembered: when nothing opens it is
    the likelier cause.
    """
    denied: OutlookGraphError | None = None
    pages = candidates.pages()
    while True:
        try:
            page = next(pages, None)
        except OutlookGraphError as e:
            if candidates.from_groups:
                raise_for_graph_error(
                    e,
                    GROUP_LISTING_DENIED,
                    GROUP_LISTING_REMEDIATION,
                    denied_row=_GROUPS_DENIED_ROW,
                    request="the group member listing",
                )
            raise_for_graph_error(
                e,
                USER_LISTING_DENIED,
                denied_row=_USERS_DENIED_ROW,
                request="the user listing",
            )
        if page is None:
            break
        if not page.mailboxes:
            continue
        mailbox = page.mailboxes[0]
        try:
            opened = opens(mailbox)
        except OutlookGraphError as e:
            if not e.is_permanent_refusal:
                _raise_for_mailbox_error(
                    e,
                    mailbox,
                    _SAMPLED_MAILBOX,
                    message=denied_one(mailbox),
                    remediation=remediation,
                    denied_row=denied_all_row,
                    unending_row=unending_row,
                )
            if e.status == 403:
                denied = e
            continue
        if opened is not None:
            return mailbox, opened
    if denied is not None:
        raise_for_graph_error(
            denied, denied_all, remediation, denied_row=denied_all_row
        )
    _raise_row(InconclusiveValidationError, nothing_to_probe.summary, nothing_to_probe)


_SAMPLED_MAIL_DENIED_ROW = _row(
    "No permission to read sampled mailboxes",
    f"The app is refused on every mailbox it tried.\n{_MAIL_GRANT}",
)


def _open_sample_mailbox(
    gateway: OutlookSourceOperations, config: OutlookConnectorConfig
) -> _Sample:
    """The first configured mailbox that opens, else the first readable one
    of the configured groups, else of the whole tenant."""
    addresses = configured_addresses(config)
    if addresses:
        return _open_configured_mailbox(gateway, addresses)
    mailbox, inbox = _first_mailbox_that(
        _Candidates(gateway, config),
        lambda mailbox: gateway.probe_mailbox(mailbox_id=mailbox.id),
        _denied,
        "The app cannot read mail in the first mailboxes it would index.",
        denied_all_row=_SAMPLED_MAIL_DENIED_ROW,
        nothing_to_probe=_NO_MAILBOX_ROW,
    )
    return _Sample.model_construct(mailbox=mailbox, inbox=inbox, name=_SAMPLED_MAILBOX)


class _OutlookCheck(CapabilityCheck[OutlookConnectorConfig]):
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
            docs_link=_OUTLOOK_DOCS_LINK,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            discovery=discovery,
            row_id=row_id,
        )


class _ConfigReadingCheck(_OutlookCheck):
    config_class = OutlookConnectorConfig


class _TokenAuthCheck(_OutlookCheck):
    """Asks Entra for a token. A blank credential field fails here too, since
    the gateway refuses to build the MSAL app without every field its
    authentication method needs."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_SIGN_IN_CHECK_ID,
            display_name="Sign in to Microsoft",
            remediation=(
                "Enter the client id, directory (tenant) id and a current "
                "client secret or certificate of the Entra app registration."
            ),
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


class _MailboxListingCheck(_OutlookCheck):
    """Lists one user. Proves ``User.Read.All``."""

    def __init__(
        self, capability: CredentialCapability = CredentialCapability.INDEXING
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=_LISTING_CHECK_ID,
            display_name="List mailboxes",
            remediation=(
                "Grant the `User.Read.All` application permission to the app "
                "registration and admin-consent it."
            ),
            validates_binding=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            _gateway(context).list_mailbox_users(page_size=_PROBE_PAGE_SIZE)
        except OutlookGraphError as e:
            raise_for_graph_error(
                e,
                USER_LISTING_DENIED,
                denied_row=_USERS_DENIED_ROW,
                request="the user listing",
            )
        return CheckOutput(summary="Tenant user list is readable")


def _tenant_mailboxes(
    gateway: OutlookSourceOperations,
) -> Generator[OutlookMailbox, None, None]:
    """The tenant's mailbox users, read one page at a time."""
    next_link: str | None = None
    for _ in range(_COUNT_PAGES):
        page: OutlookMailboxPage = gateway.list_mailbox_users(next_link=next_link)
        yield from page.mailboxes
        next_link = page.next_link
        if next_link is None:
            return
    raise InconclusiveValidationError(
        f"The tenant's user listing did not end within {_COUNT_PAGES} pages.",
        summary="User list did not end",
        description="Microsoft kept returning short pages.\nRe-run the checks later.",
    )


class _MailboxCountCheck(_ConfigReadingCheck):
    """Counts the enabled users with a mail address: the mailboxes indexing
    walks in every-mailbox mode. It does not probe each mailbox, so a mailbox
    outside the app's Exchange scope still counts. It shares the "List
    mailboxes" row, whose probe reads one user. A config that lists mailboxes
    or groups walks only those, so the tenant count does not apply to it."""

    def __init__(self) -> None:
        super().__init__(
            check_id="outlook_mailbox_count",
            display_name="List mailboxes",
            remediation=(
                "Grant the `User.Read.All` application permission to the app "
                "registration and admin-consent it."
            ),
            discovery=True,
            row_id=_LISTING_CHECK_ID,
        )

    def applies(self, form_state: FormState[OutlookConnectorConfig]) -> bool:
        config: OutlookConnectorConfig = form_state.config
        return not configured_addresses(config) and not configured_groups(config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            finding: CountFinding = bounded_count(
                _tenant_mailboxes(_gateway(context)),
                key=CheckFindingKey.READABLE_MAILBOXES,
                cap=MAX_FINDING_OPTIONS,
            )
        except OutlookGraphError as e:
            raise_for_graph_error(
                e,
                USER_LISTING_DENIED,
                denied_row=_USERS_DENIED_ROW,
                request="the user listing",
            )
        count: str = f"{finding.count}+" if finding.at_least else str(finding.count)
        return CheckOutput(
            summary=f"Up to {count} {'mailbox' if count == '1' else 'mailboxes'}",
            findings=[finding],
        )


_ATTACHMENTS_NOT_VERIFIED_NO_ATTACHMENTS = (
    "The sample message has no attachments, so attachment reads were not tested."
)
_ATTACHMENTS_NOT_VERIFIED_GONE = (
    "The sample message was not found when the check read its attachments, so "
    "attachment reads were not tested."
)


class _MailReadCheck(_ConfigReadingCheck):
    """Reads folders, one delta page, one message body and, when that message
    has any, its attachment records. Proves ``Mail.Read`` and that the mailbox
    is inside the app's Exchange scope. A config-less run reads any mailbox.
    An empty mailbox is INCOMPLETE; a sample without attachments passes with
    a caveat."""

    def __init__(self) -> None:
        super().__init__(
            check_id="outlook_mail_read",
            display_name="Sample mail",
            remediation=EXCHANGE_SCOPE_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = _gateway(context)
        sample: _Sample = _open_sample_mailbox(gateway, self.config(context))
        mailbox: OutlookMailbox = sample.mailbox
        try:
            gateway.get_well_known_folder(
                mailbox_id=mailbox.id, name=_PROBE_WELL_KNOWN_FOLDER
            )
            gateway.list_child_folders(
                mailbox_id=mailbox.id, page_size=_PROBE_PAGE_SIZE
            )
            gateway.fetch_folder_delta_page(
                mailbox_id=mailbox.id,
                folder_id=sample.inbox.id,
                page_size=_PROBE_PAGE_SIZE,
            )
        except OutlookGraphError as e:
            _raise_for_mailbox_error(
                e, mailbox, sample.name, unending_row=_MESSAGES_UNENDING_ROW
            )

        try:
            message = gateway.read_any_message(mailbox_id=mailbox.id)
        except OutlookGraphError as e:
            _raise_for_mailbox_error(
                e,
                mailbox,
                sample.name,
                message=_BODY_DENIED,
                denied_row=_row(
                    "Mail bodies are not readable",
                    f"The app can list mail but not read message text.\n{_MAIL_GRANT}",
                ),
                unending_row=_MESSAGES_UNENDING_ROW,
                request="the message read",
            )
        passed: str = _line("Read mail in ", sample.name)
        if message is None:
            # A mailbox the walk sampled stays unnamed.
            subject: str = (
                f"`{mailbox.address}`"
                if sample.name != _SAMPLED_MAILBOX
                else "The sampled mailbox"
            )
            raise InconclusiveValidationError(
                f"{subject} holds no messages, so the check did not verify that "
                "the app can read message bodies and attachments.",
                summary=_line("No mail found in ", sample.name),
                description=(
                    "The mailbox is empty.\nAdd a mailbox that has mail to "
                    "Mailboxes, then run the checks again."
                ),
            )
        if not message.has_attachments:
            return CheckOutput(
                summary=passed,
                advisories=[
                    CheckAdvisory(message=_ATTACHMENTS_NOT_VERIFIED_NO_ATTACHMENTS)
                ],
            )
        try:
            gateway.list_message_attachments(
                mailbox_id=mailbox.id, message_id=message.id, limit=1
            )
        except OutlookGraphError as e:
            # The sample can be deleted between the two reads. The body read
            # already proved the grant, so that is not a failure.
            if e.status == 404:
                return CheckOutput(
                    summary=passed,
                    advisories=[CheckAdvisory(message=_ATTACHMENTS_NOT_VERIFIED_GONE)],
                )
            if e.status == _LOCKED_STATUS:
                raise ConnectorValidationError(
                    f"`{mailbox.address}` refused the attachment read ({e.code}).",
                    summary=_line("Mailbox is locked: ", sample.name),
                    description="The mailbox refused the attachment read.\nRe-run "
                    "the checks.",
                ) from e
            _raise_for_mailbox_error(
                e,
                mailbox,
                sample.name,
                denied_row=_row(
                    "Attachments are not readable",
                    "The app can read messages but not their attachments.\n"
                    f"{_MAIL_GRANT}",
                ),
                request="the attachment read",
            )
        return CheckOutput(summary=passed)


_EVENT_BODY_DENIED_ROW = _row(
    "Event details are not readable",
    f"The app can list events but not read their text.\n{_CALENDAR_GRANT}",
)


def _event_with_body(
    gateway: OutlookSourceOperations, mailbox: OutlookMailbox, name: str
) -> OutlookEvent | None:
    """One event with its body, None for an empty calendar. A body Graph refuses
    or withholds is ``Calendars.ReadBasic.All`` at work, which another mailbox
    cannot cure, so that fails at once."""
    try:
        sample = gateway.read_any_event(mailbox_id=mailbox.id)
    except OutlookGraphError as e:
        _raise_for_mailbox_error(
            e,
            mailbox,
            name,
            message=_EVENT_BODY_DENIED,
            remediation=CALENDAR_READ_REMEDIATION,
            denied_row=_EVENT_BODY_DENIED_ROW,
            unending_row=_EVENTS_UNENDING_ROW,
            request="the event read",
        )
    if sample is not None and not sample.body_present:
        _raise_row(
            InsufficientPermissionsError,
            f"{_EVENT_BODY_DENIED} {CALENDAR_READ_REMEDIATION}",
            _EVENT_BODY_DENIED_ROW,
        )
    return sample


_NO_EVENTS_ROW = _row(
    "No events found to test",
    "None of the sampled calendars holds an event.\nAdd a mailbox that has "
    "events to Mailboxes, then run the checks again.",
)


class _CalendarReadCheck(_ConfigReadingCheck):
    """Reads one page of one mailbox's calendar view, the call indexing makes,
    then one event with its body, which ``Calendars.ReadBasic.All`` withholds.
    Together they prove ``Calendars.Read``. An empty calendar proves the
    listing only, so in every-mailbox mode the walk moves on to one with
    events, and a calendar with no events is INCOMPLETE. A connector that does
    not index calendars needs no such grant, so the check does not apply."""

    def __init__(self) -> None:
        super().__init__(
            check_id="outlook_calendar_read",
            display_name="Sample calendars",
            remediation=CALENDAR_READ_REMEDIATION,
            requires_connector_config=True,
        )

    def applies(self, form_state: FormState[OutlookConnectorConfig]) -> bool:
        return form_state.config.include_calendar

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config = self.config(context)
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
            return _event_with_body(gateway, mailbox, _SAMPLED_MAILBOX)

        addresses = configured_addresses(config)
        if addresses:
            sample: _Sample = _open_configured_mailbox(gateway, addresses)
            try:
                view(sample.mailbox)
            except OutlookGraphError as e:
                _raise_for_mailbox_error(
                    e,
                    sample.mailbox,
                    sample.name,
                    message=_calendar_denied(sample.mailbox),
                    remediation=CALENDAR_READ_REMEDIATION,
                    denied_row=_calendar_denied_row(sample.name),
                    unending_row=_EVENTS_UNENDING_ROW,
                    request="the calendar read",
                )
            if _event_with_body(gateway, sample.mailbox, sample.name) is None:
                _raise_row(
                    InconclusiveValidationError,
                    f"`{sample.mailbox.address}` holds no event, so the check did "
                    "not verify that the app can read event bodies.",
                    _NO_EVENTS_ROW,
                )
            return CheckOutput(summary=_line("Read an event in ", sample.name))
        _first_mailbox_that(
            _Candidates(gateway, config),
            calendar_with_event,
            _calendar_denied,
            "The app cannot read the calendar of the first mailboxes it would index.",
            denied_all_row=_row(
                "No permission to read sampled calendars",
                f"The app is refused on every calendar it tried.\n{_CALENDAR_GRANT}",
            ),
            nothing_to_probe=_NO_EVENTS_ROW,
            remediation=CALENDAR_READ_REMEDIATION,
            unending_row=_EVENTS_UNENDING_ROW,
        )
        return CheckOutput(summary=_line("Read an event in ", _SAMPLED_MAILBOX))


def _calendar_denied_row(name: str) -> MicrosoftRowText:
    return _row(
        _line("No permission to read calendar of ", name),
        f"The app cannot read this mailbox's calendar.\n{_CALENDAR_GRANT}",
    )


def _mailbox_problem_row(problem: MailboxProblem) -> MicrosoftRowText:
    if problem.status is None:
        return _mailbox_not_found_row(problem.address)
    if problem.status == 403:
        return _mail_denied_row(problem.address)
    return _unusable_mailbox_row(problem.address)


class _ConfiguredMailboxesCheck(_ConfigReadingCheck):
    """Resolves and probes every explicitly configured mailbox. Some
    unreachable is INCOMPLETE, and the samples open the reachable ones; none
    reachable FAILS."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_CONFIGURED_MAILBOXES_CHECK_ID,
            display_name="Find selected mailboxes",
            remediation=f"{MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}",
            requires_connector_config=True,
        )

    def applies(self, form_state: FormState[OutlookConnectorConfig]) -> bool:
        return bool(configured_addresses(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        addresses = configured_addresses(self.config(context))
        problems: list[MailboxProblem] = describe_unavailable_mailboxes(
            _gateway(context), addresses
        )
        if not problems:
            return CheckOutput(
                summary=(
                    "1 selected mailbox open"
                    if len(addresses) == 1
                    else f"All {len(addresses)} selected mailboxes open"
                )
            )
        message: str = (
            "These mailboxes cannot be indexed: "
            + ", ".join(problem.describe() for problem in problems)
            + f". {MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}"
        )
        first: MicrosoftRowText = _mailbox_problem_row(problems[0])
        if len(problems) == len(addresses):
            _raise_row(
                ConnectorValidationError,
                message,
                first
                if len(problems) == 1
                else _row(
                    "No selected mailbox found",
                    "None of the selected mailboxes is visible to this account.\n"
                    + f"{MAILBOX_UNAVAILABLE_REMEDIATION}",
                ),
            )
        if len(problems) == 1:
            return CheckOutput(
                summary=first.summary, description=first.description, partial=True
            )
        return CheckOutput(
            summary=f"{len(problems)} of {len(addresses)} mailboxes not reachable",
            description=(
                "Some selected mailboxes cannot be opened: no such user, no "
                "mailbox, or outside the app's Exchange scope.\nNot reachable: "
                + ", ".join(problem.address for problem in problems)
                + "."
            ),
            partial=True,
        )


def _group_problem_row(problem: GroupProblem) -> MicrosoftRowText:
    return _row(
        _line("Group not found: ", problem.identifier),
        f"{problem.describe()}.\nUse the group's object ID in Mailbox Groups.",
    )


class _ConfiguredGroupsCheck(_ConfigReadingCheck):
    """Each configured group names exactly one Entra group the app can read.
    Some unusable is INCOMPLETE; none usable FAILS."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_CONFIGURED_GROUPS_CHECK_ID,
            display_name="Find selected groups",
            remediation=f"{GROUP_UNAVAILABLE_REMEDIATION} {GROUP_LISTING_REMEDIATION}",
            requires_connector_config=True,
        )

    def applies(self, form_state: FormState[OutlookConnectorConfig]) -> bool:
        return bool(configured_groups(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        groups = configured_groups(self.config(context))
        try:
            problems: list[GroupProblem] = describe_unavailable_groups(
                _gateway(context), groups, denied_row=_GROUPS_DENIED_ROW
            )
        except RuntimeError as e:
            raise UnexpectedValidationError(
                str(e),
                summary="Group lookup did not end",
                description=(
                    "Microsoft kept paging the group lookup.\nUse the group's "
                    "object ID in Mailbox Groups."
                ),
            ) from e
        if not problems:
            return CheckOutput(
                summary=(
                    "1 selected group found"
                    if len(groups) == 1
                    else f"All {len(groups)} selected groups found"
                )
            )
        message: str = (
            "These groups cannot be used: "
            + ", ".join(problem.describe() for problem in problems)
            + f". {GROUP_UNAVAILABLE_REMEDIATION}"
        )
        first: MicrosoftRowText = _group_problem_row(problems[0])
        if len(problems) == len(groups):
            _raise_row(
                ConnectorValidationError,
                message,
                first
                if len(problems) == 1
                else _row(
                    "No selected group found",
                    "None of the selected groups is visible to this account.\n"
                    "Use each group's object ID in Mailbox Groups.",
                ),
            )
        if len(problems) == 1:
            return CheckOutput(
                summary=first.summary, description=first.description, partial=True
            )
        return CheckOutput(
            summary=f"{len(problems)} of {len(groups)} groups not found",
            description=(
                "Some Mailbox Groups entries do not name exactly one Entra group: "
                + ", ".join(problem.identifier for problem in problems)
                + ".\nUse each group's object ID in Mailbox Groups."
            ),
            partial=True,
        )


def build_outlook_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenAuthCheck(),
        _MailboxListingCheck(),
        _MailboxCountCheck(),
        _ConfiguredMailboxesCheck(),
        _ConfiguredGroupsCheck(),
        _MailReadCheck(),
        _CalendarReadCheck(),
    ]


def build_outlook_doc_permission_sync_checks() -> list[CapabilityCheck]:
    """The permission walk shares indexing's mail and calendar grants, proven by
    its checks in the same run, so this capability proves only the user listing
    every owner address comes from. The runner executes a check id once and
    mirrors the outcome onto each capability that registers it."""
    return [_MailboxListingCheck(CredentialCapability.DOC_PERMISSION_SYNC)]
