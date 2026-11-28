"""Named permission sync checks for Zendesk. The doc sync needs an admin's
token: only admins read the ticket export, every restricted article, and the
emails of the users a ticket names."""

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.zendesk.capability_checks import (
    PROBE_PAGE_SIZE,
    gateway_from_context,
    probe,
)
from onyx.connectors.zendesk.config import ZendeskConnectorConfig, ZendeskContentType
from onyx.connectors.zendesk.models import ZendeskRole, ZendeskTicketPage, ZendeskUser
from onyx.connectors.zendesk.source_operations import ZendeskSourceOperations

_ADMIN_REMEDIATION: str = "Use the API token of a Zendesk admin."
# Enough tickets that one is likely live when the oldest were deleted.
_TICKET_SAMPLE_SIZE: int = 10


class _AdminCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner reads the user once.
            check_id="zendesk_perm_sync_admin",
            display_name="The token belongs to an admin",
            requires_connector_instance=False,
            remediation=_ADMIN_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        me: ZendeskUser = probe(
            gateway_from_context(context).get_me, "Zendesk did not answer."
        )
        if me.role != ZendeskRole.ADMIN:
            raise InsufficientPermissionsError(
                f"The token's user is a Zendesk {me.role or 'user'}, not an admin, "
                f"so restricted articles and tickets would stay private. "
                f"{_ADMIN_REMEDIATION}"
            )


class _ArticleAccessCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="zendesk_article_access",
            display_name="Article visibility is readable",
            requires_connector_instance=False,
            remediation=_ADMIN_REMEDIATION,
        )

    def applies(self, form_state: FormState[ZendeskConnectorConfig]) -> bool:
        return form_state.config.content_type == ZendeskContentType.ARTICLES

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: ZendeskSourceOperations = gateway_from_context(context)

        def read_first_article_access() -> None:
            page = gateway.get_article_page(start_time=0, page_size=PROBE_PAGE_SIZE)
            if page.data:
                gateway.is_article_public(article_id=page.data[0]["id"])

        probe(read_first_article_access, "The token cannot read articles.")


class _TicketAccessCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="zendesk_ticket_access",
            display_name="Ticket users and comments are readable",
            requires_connector_instance=False,
            remediation=_ADMIN_REMEDIATION,
        )

    def applies(self, form_state: FormState[ZendeskConnectorConfig]) -> bool:
        return form_state.config.content_type == ZendeskContentType.TICKETS

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: ZendeskSourceOperations = gateway_from_context(context)

        def read_first_ticket_access() -> ZendeskTicketPage:
            page = gateway.get_ticket_page(
                start_time=0, per_page=_TICKET_SAMPLE_SIZE, include_access=True
            )
            # The export lists deleted tickets, whose comments are gone.
            live = next(
                (ticket for ticket in page.data if ticket.get("status") != "deleted"),
                None,
            )
            if live is not None:
                gateway.list_ticket_comments(ticket_id=live["id"])
            return page

        page: ZendeskTicketPage = probe(
            read_first_ticket_access, "The token cannot read ticket access."
        )
        # A ticket always names a requester, but shared tickets from another
        # Zendesk name placeholder users without emails, so this only warns.
        if page.data and not any(user.email for user in page.users):
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            "No user email was readable on the sampled tickets, so "
                            "only groups may be granted. Check that the token "
                            "belongs to an admin."
                        )
                    )
                ]
            )
        return None


def build_zendesk_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _AdminCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _ArticleAccessCheck(),
        _TicketAccessCheck(),
    ]
