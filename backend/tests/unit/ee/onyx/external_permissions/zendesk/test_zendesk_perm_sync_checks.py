from typing import Any
from unittest.mock import MagicMock

from ee.onyx.external_permissions.zendesk.capability_checks import (
    build_zendesk_doc_permission_sync_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.zendesk.models import ZendeskTicketPage, ZendeskUser
from onyx.connectors.zendesk.source_operations import ZendeskSourceOperations


def _run_ticket_check(page: ZendeskTicketPage) -> tuple[CheckOutput | None, Any]:
    gateway = MagicMock(spec=ZendeskSourceOperations)
    gateway.get_ticket_page.return_value = page
    gateway.list_ticket_comments.return_value = []
    context = CapabilityCheckContext(
        source=DocumentSource.ZENDESK,
        credential_json={},
        connector_specific_config={"content_type": "tickets"},
        source_operations=gateway,
    )
    check = next(
        c
        for c in build_zendesk_doc_permission_sync_checks()
        if c.check_id == "zendesk_ticket_access"
    )
    return check.run(context), gateway


def test_ticket_check_reads_comments_of_a_live_ticket() -> None:
    page = ZendeskTicketPage(
        data=[{"id": 1, "status": "deleted"}, {"id": 2, "status": "open"}],
        meta={"end_time": 1},
        has_more=False,
        users=[ZendeskUser(id=5, email="a@example.com")],
    )
    output, gateway = _run_ticket_check(page)
    assert output is None
    gateway.list_ticket_comments.assert_called_once_with(ticket_id=2)


def test_ticket_check_only_warns_without_user_emails() -> None:
    """Shared tickets from another Zendesk name users without emails."""
    page = ZendeskTicketPage(
        data=[{"id": 2, "status": "open"}],
        meta={"end_time": 1},
        has_more=False,
        users=[ZendeskUser(id=5)],
    )
    output, _ = _run_ticket_check(page)
    assert output is not None
    assert output.advisories
