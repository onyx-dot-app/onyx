"""Named permission sync checks for Zendesk. The doc sync needs an admin's
token: only admins read the ticket export, every restricted article, and the
emails of the users a ticket names."""

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
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

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: ZendeskSourceOperations = gateway_from_context(context)

        def read_first_ticket_access() -> ZendeskTicketPage:
            page = gateway.get_ticket_page(
                start_time=0, per_page=PROBE_PAGE_SIZE, include_access=True
            )
            if page.data:
                gateway.list_ticket_comments(ticket_id=page.data[0]["id"])
            return page

        page: ZendeskTicketPage = probe(
            read_first_ticket_access, "The token cannot read ticket access."
        )
        # A ticket always names a requester. No user email at all means Zendesk
        # hides them from this token, and only groups would be granted.
        if page.data and not any(user.email for user in page.users):
            raise InsufficientPermissionsError(
                f"Zendesk shows no user emails to this token. {_ADMIN_REMEDIATION}"
            )


def build_zendesk_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _AdminCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _ArticleAccessCheck(),
        _TicketAccessCheck(),
    ]
