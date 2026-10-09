"""The HubSpot permission reader asks who may view each record and turns the
viewer ids into the emails of known users. The connector's walk asks for records
in the batches HubSpot accepts and hands the emails out under the ids indexing
gives the records."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT, HubSpotConnector
from onyx.connectors.hubspot.models import (
    HubSpotPage,
    HubSpotRecord,
    HubSpotUser,
)
from onyx.connectors.hubspot.permissions import HubSpotPermissionReader
from onyx.connectors.hubspot.source_operations import (
    PERMITTED_USERS_BATCH_SIZE,
    HubSpotApiError,
    HubSpotSourceOperations,
)
from onyx.connectors.models import HierarchyNode, SlimDocument

CONNECTOR = "onyx.connectors.hubspot.connector"
PORTAL = "46399533"
USER_LISTING = "user listing"
MOMENT = datetime(2024, 6, 6, tzinfo=timezone.utc)


def _ops() -> MagicMock:
    return create_autospec(HubSpotSourceOperations, instance=True)


def _emails(*emails: str) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(emails),
        external_user_group_ids=set(),
        is_public=False,
    )


def test_viewers_are_asked_for_together_under_the_portal() -> None:
    ops = _ops()
    ops.get_record_viewers.return_value = {"1": {10, 11}, "2": set()}

    viewers = HubSpotPermissionReader(ops, PORTAL).viewers(
        HubSpotObjectType.DEALS, ["1", "2"]
    )

    assert viewers == {"1": {10, 11}, "2": set()}
    ops.get_record_viewers.assert_called_once_with(
        portal_id=PORTAL, object_type=HubSpotObjectType.DEALS, record_ids=["1", "2"]
    )


def test_the_user_listing_follows_the_cursor() -> None:
    ops = _ops()
    ops.list_users.side_effect = [
        HubSpotPage(items=[HubSpotUser(id=1)], next_after="c1"),
        HubSpotPage(items=[HubSpotUser(id=2)]),
    ]

    users = list(HubSpotPermissionReader(ops, PORTAL).list_users())

    assert [user.id for user in users] == [1, 2]
    assert [c.kwargs["after"] for c in ops.list_users.call_args_list] == [None, "c1"]


def test_access_uses_listed_emails_and_looks_up_the_rest_once() -> None:
    ops = _ops()
    ops.list_users.return_value = HubSpotPage(
        items=[
            HubSpotUser(id=10, email="Ada@Example.com"),
            HubSpotUser(id=11, email="bob@example.com"),
        ]
    )
    looked_up = {
        12: HubSpotUser(id=12, email="cy@example.com"),
        13: None,
        14: HubSpotUser(id=14, email="app-1@appserviceaccount.na2.hubspot.com"),
    }
    ops.get_user.side_effect = lambda user_id: looked_up[user_id]

    reader = HubSpotPermissionReader(ops, PORTAL)
    first = reader.access_for([10, 12, 13, 14])
    second = reader.access_for([11, 13])

    assert first == _emails("ada@example.com", "cy@example.com")
    assert second == _emails("bob@example.com")
    ops.list_users.assert_called_once()
    assert [c.kwargs["user_id"] for c in ops.get_user.call_args_list] == [12, 13, 14]


def _connector(ops: MagicMock) -> HubSpotConnector:
    connector = HubSpotConnector(object_types=["deals"])
    connector._ops = ops
    connector._portal_id = PORTAL
    return connector


def _slim(doc: SlimDocument | HierarchyNode) -> SlimDocument:
    assert isinstance(doc, SlimDocument)
    return doc


def _page(record_ids: list[str], **properties: str) -> HubSpotPage[HubSpotRecord]:
    return HubSpotPage(
        items=[
            HubSpotRecord(
                id=record_id,
                properties=properties,
                created_at=MOMENT,
                updated_at=MOMENT,
            )
            for record_id in record_ids
        ]
    )


def test_the_walk_yields_document_ids_with_their_viewers_emails() -> None:
    reader = MagicMock()
    reader.viewers.side_effect = lambda _object_type, ids: {i: {int(i)} for i in ids}
    reader.access_for.side_effect = lambda ids: _emails(
        *(f"{i}@example.com" for i in ids)
    )
    ops = _ops()
    ops.list_records.return_value = _page(["1", "2", "3"])

    with (
        patch(f"{CONNECTOR}.HubSpotPermissionReader", return_value=reader),
        patch(f"{CONNECTOR}._SLIM_BATCH_SIZE", 2),
    ):
        batches = list(_connector(ops).retrieve_all_slim_docs_perm_sync())

    assert [[_slim(doc).id for doc in batch] for batch in batches] == [
        ["hubspot_deal_1", "hubspot_deal_2"],
        ["hubspot_deal_3"],
    ]
    assert _slim(batches[1][0]).external_access == _emails("3@example.com")
    reader.viewers.assert_called_once_with(HubSpotObjectType.DEALS, ["1", "2", "3"])


def test_a_listing_from_a_start_searches_open_ended_with_the_modified_date() -> None:
    ops = _ops()
    ops.search_records.return_value = _page(["1"])

    [batch] = list(_connector(ops).retrieve_all_slim_docs(start=1_700_000_000))

    assert [_slim(doc).id for doc in batch] == ["hubspot_deal_1"]
    kwargs = ops.search_records.call_args.kwargs
    assert kwargs["properties"] == ["hs_object_id", "hs_lastmodifieddate"]
    assert kwargs["modified_after"].timestamp() == 1_700_000_000
    assert kwargs["modified_before"] is None


def test_a_listing_the_search_cannot_complete_raises_instead_of_shrinking() -> None:
    ops = _ops()
    ops.search_records.return_value = _page(
        [str(i) for i in range(HUBSPOT_SEARCH_LIMIT)],
        hs_lastmodifieddate="2024-01-01T00:00:00+00:00",
    )

    with pytest.raises(RuntimeError, match="did not advance"):
        list(_connector(ops).retrieve_all_slim_docs(start=1_704_067_200))


def test_the_walk_refreshes_the_heartbeat_per_viewer_call_and_honors_stop() -> None:
    reader = MagicMock()
    reader.viewers.side_effect = lambda _object_type, ids: {i: set() for i in ids}
    reader.access_for.return_value = ExternalAccess.empty()
    ops = _ops()
    ops.list_records.return_value = _page(
        [str(i) for i in range(PERMITTED_USERS_BATCH_SIZE + 1)]
    )
    callback = MagicMock()
    callback.should_stop.side_effect = [False, True]

    with (
        patch(f"{CONNECTOR}.HubSpotPermissionReader", return_value=reader),
        pytest.raises(RuntimeError, match="Stop signal"),
    ):
        list(_connector(ops).retrieve_all_slim_docs_perm_sync(callback=callback))

    callback.progress.assert_called_once()
    reader.viewers.assert_called_once()


def test_the_prune_listing_carries_ids_only_and_never_asks_for_viewers() -> None:
    ops = _ops()
    ops.list_records.return_value = _page(["1", "2"])

    with patch(f"{CONNECTOR}.HubSpotPermissionReader") as reader_factory:
        [batch] = list(_connector(ops).retrieve_all_slim_docs())

    assert [(_slim(doc).id, _slim(doc).external_access) for doc in batch] == [
        ("hubspot_deal_1", None),
        ("hubspot_deal_2", None),
    ]
    assert ops.list_records.call_args.kwargs["properties"] == ["hs_object_id"]
    reader_factory.assert_not_called()


def test_the_probe_turns_a_refusal_into_insufficient_permissions() -> None:
    ops = _ops()
    ops.list_users.side_effect = HubSpotApiError(USER_LISTING, 403, {}, "")

    with pytest.raises(InsufficientPermissionsError, match=USER_LISTING):
        _connector(ops).probe_permission_sync_scopes()

    ops.list_users.assert_called_once_with(limit=1)
