"""Gateway, record and error builders that the HubSpot capability check tests share."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.hubspot.models import HubSpotPage, HubSpotRecord, HubSpotUser
from onyx.connectors.hubspot.source_operations import (
    HubSpotApiError,
    HubSpotSourceOperations,
)

MOMENT = datetime(2024, 6, 6, tzinfo=timezone.utc)


def make_record(record_id: str) -> HubSpotRecord:
    return HubSpotRecord(id=record_id, created_at=MOMENT, updated_at=MOMENT)


def api_refusal(operation: str, status: int) -> HubSpotApiError:
    return HubSpotApiError(operation, status, None, "")


def healthy_gateway() -> MagicMock:
    """A healthy portal with one record of each type, one note and one user."""
    gateway: MagicMock = create_autospec(HubSpotSourceOperations, instance=True)
    gateway.get_portal_id.return_value = "46399533"
    gateway.list_records.return_value = HubSpotPage(items=[make_record("1")])
    gateway.search_records.return_value = HubSpotPage(items=[make_record("1")])
    gateway.read_records.return_value = [make_record("1")]
    gateway.list_associations.return_value = HubSpotPage(items=["9"])
    gateway.list_users.return_value = HubSpotPage(items=[HubSpotUser(id=7)])
    gateway.get_user.return_value = HubSpotUser(id=7, email="ada@example.com")
    gateway.get_record_viewers.return_value = {"1": {7}}
    return gateway
