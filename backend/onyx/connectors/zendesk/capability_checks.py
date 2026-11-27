"""Named indexing checks for Zendesk, composed from the gateway's operations.

Indexing needs a token Zendesk accepts, then readable Help Center articles or
readable tickets and comments, depending on the configured content type.
"""

from collections.abc import Callable
from typing import TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.zendesk.config import ZendeskConnectorConfig, ZendeskContentType
from onyx.connectors.zendesk.source_operations import ZendeskSourceOperations

T = TypeVar("T")

PROBE_PAGE_SIZE: int = 1


def gateway_from_context(context: CapabilityCheckContext) -> ZendeskSourceOperations:
    if not isinstance(context.source_operations, ZendeskSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def probe(action: Callable[[], T], denied: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only other failures are wrapped."""
    try:
        return action()
    except (RuntimeError, ValueError, KeyError) as error:
        raise UnexpectedValidationError(f"{denied} {error}") from error


class _TokenCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="zendesk_token",
            display_name="Zendesk accepts the subdomain, email and token",
            requires_connector_instance=False,
            validates_binding=True,
            remediation=(
                "Check the subdomain, the email of the user the token belongs to, "
                "and that the API token is active."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        probe(gateway_from_context(context).get_me, "Zendesk did not answer.")


class _ArticlesCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="zendesk_articles",
            display_name="Help Center articles are readable",
            requires_connector_instance=False,
            remediation=(
                "Use a token of a Guide admin or an agent who can read the Help Center."
            ),
        )

    def applies(self, form_state: FormState[ZendeskConnectorConfig]) -> bool:
        return form_state.config.content_type == ZendeskContentType.ARTICLES

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: ZendeskSourceOperations = gateway_from_context(context)

        def read_first_article() -> bool:
            """Whether an article's author was read."""
            gateway.list_content_tags(page_size=PROBE_PAGE_SIZE, max_pages=1)
            page = gateway.get_article_page(start_time=0, page_size=PROBE_PAGE_SIZE)
            author_id = page.data[0].get("author_id") if page.data else None
            if not author_id:
                return False
            return gateway.get_user(user_id=author_id) is not None

        if probe(read_first_article, "The token cannot read articles."):
            return None
        return CheckOutput(
            advisories=[
                CheckAdvisory(
                    message=(
                        "No article author could be read, so documents will have "
                        "no owner. Use a token that can read users."
                    )
                )
            ]
        )


class _TicketsCheck(CapabilityCheck[ZendeskConnectorConfig]):
    config_class = ZendeskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="zendesk_tickets",
            display_name="Tickets and comments are readable",
            requires_connector_instance=False,
            remediation=(
                "Use a token of an admin. The ticket export needs admin access, and "
                "the account needs an active Support product."
            ),
        )

    def applies(self, form_state: FormState[ZendeskConnectorConfig]) -> bool:
        return form_state.config.content_type == ZendeskContentType.TICKETS

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: ZendeskSourceOperations = gateway_from_context(context)

        def read_first_ticket() -> bool:
            """Whether a ticket's comments were read."""
            page = gateway.get_ticket_page(start_time=0, per_page=PROBE_PAGE_SIZE)
            if not page.data:
                return False
            gateway.list_ticket_comments(ticket_id=page.data[0]["id"])
            return True

        if probe(read_first_ticket, "The token cannot read tickets."):
            return None
        return CheckOutput(
            advisories=[
                CheckAdvisory(
                    message="No ticket to read, so comment access was not checked."
                )
            ]
        )


def build_zendesk_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _ArticlesCheck(), _TicketsCheck()]
