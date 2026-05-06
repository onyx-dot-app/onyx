"""Unit tests for Freshdesk connector handling of nullable timestamp fields.

Reproduces the production traceback:

    File "/app/onyx/connectors/freshdesk/connector.py", line 131
        due_by = datetime.fromisoformat(ticket["due_by"].replace("Z", "+00:00"))
    AttributeError: 'NoneType' object has no attribute 'replace'

The Freshdesk API explicitly documents ``due_by`` (and ``fr_due_by``) as
nullable. This is dramatically more frequent on accounts created after
25 Aug 2025, where the new SLA engine recalculates ``due_by`` for a few
seconds after every ticket update — and our connector polls by
``updated_since``, so it specifically targets the tickets most likely to be
in that recalculation window.
"""

from typing import Any

from onyx.connectors.freshdesk.connector import _create_doc_from_ticket
from onyx.connectors.freshdesk.connector import _create_metadata_from_ticket


def _ticket(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 42,
        "subject": "Website unresponsive",
        "description_text": "Some details on the issue ...",
        "status": 2,
        "priority": 1,
        "source": 2,
        "due_by": "2024-01-15T11:30:00Z",
        "updated_at": "2024-01-10T11:30:00Z",
    }
    base.update(overrides)
    return base


class TestNullDueBy:
    def test_metadata_omits_overdue_when_due_by_is_null(self) -> None:
        metadata = _create_metadata_from_ticket(_ticket(due_by=None))
        assert "overdue" not in metadata

    def test_metadata_omits_overdue_when_due_by_is_missing(self) -> None:
        ticket = _ticket()
        del ticket["due_by"]
        metadata = _create_metadata_from_ticket(ticket)
        assert "overdue" not in metadata

    def test_metadata_includes_overdue_when_due_by_is_present(self) -> None:
        metadata = _create_metadata_from_ticket(_ticket(due_by="2024-01-15T11:30:00Z"))
        # 2024-01-15 is in the past, so the ticket is overdue
        assert metadata["overdue"] == "True"

    def test_doc_creation_does_not_crash_on_null_due_by(self) -> None:
        doc = _create_doc_from_ticket(_ticket(due_by=None), domain="example")
        assert doc.semantic_identifier == "Website unresponsive"
        assert "overdue" not in doc.metadata


class TestNullUpdatedAt:
    def test_doc_creation_does_not_crash_on_null_updated_at(self) -> None:
        doc = _create_doc_from_ticket(_ticket(updated_at=None), domain="example")
        assert doc.doc_updated_at is None
