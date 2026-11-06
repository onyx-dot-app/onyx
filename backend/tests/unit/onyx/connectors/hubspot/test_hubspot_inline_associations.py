"""Indexing reads associations listed inline with a record and falls back to
batched v4 association reads when they were not fetched or HubSpot paged them. The
modified-date search pages through the gateway and continues past HubSpot's
10,000-result cap."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.exceptions import (
    CredentialInvalidError,
    UnexpectedValidationError,
)
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT, HubSpotConnector
from onyx.connectors.hubspot.models import (
    HubSpotAssociationIds,
    HubSpotPage,
    HubSpotRecord,
)
from onyx.connectors.hubspot.source_operations import (
    HubSpotApiError,
    HubSpotSourceOperations,
)
from onyx.connectors.models import Document

MODIFIED = "hs_lastmodifieddate"
MOMENT = datetime(2024, 6, 6, tzinfo=timezone.utc)


def _connector() -> tuple[HubSpotConnector, MagicMock]:
    connector = HubSpotConnector()
    ops = create_autospec(HubSpotSourceOperations, instance=True)
    connector._ops = ops
    connector._portal_id = "portal"
    return connector, ops


def _record(
    record_id: str = "1",
    associations: dict[str, HubSpotAssociationIds] | None = None,
    modified: str | None = None,
) -> HubSpotRecord:
    return HubSpotRecord(
        id=record_id,
        properties={MODIFIED: modified} if modified else {},
        created_at=MOMENT,
        updated_at=MOMENT,
        associations=associations,
    )


def _inline(ids: list[str], has_more: bool = False) -> HubSpotAssociationIds:
    return HubSpotAssociationIds(ids=ids, has_more=has_more)


class TestExtractInlineAssociationIds:
    def test_returns_ids_when_complete(self) -> None:
        connector, _ = _connector()
        record = _record(associations={"contacts": _inline(["1", "2", "3"])})

        result = connector._extract_inline_association_ids(
            record, HubSpotObjectType.CONTACTS
        )

        assert result == ["1", "2", "3"]

    def test_returns_empty_list_when_type_not_present(self) -> None:
        connector, _ = _connector()
        record = _record(associations={"companies": _inline(["5"])})

        result = connector._extract_inline_association_ids(
            record, HubSpotObjectType.CONTACTS
        )

        assert result == []

    def test_returns_none_when_associations_were_not_fetched(self) -> None:
        connector, _ = _connector()

        result = connector._extract_inline_association_ids(
            _record(), HubSpotObjectType.CONTACTS
        )

        assert result is None

    def test_returns_none_when_hubspot_paged_them(self) -> None:
        """A paged inline list is incomplete, so the caller falls back to v4."""
        connector, _ = _connector()
        record = _record(associations={"contacts": _inline(["1", "2"], has_more=True)})

        result = connector._extract_inline_association_ids(
            record, HubSpotObjectType.CONTACTS
        )

        assert result is None


class TestLinkedRecords:
    def test_inline_ids_drive_one_read_for_the_batch_and_skip_v4(self) -> None:
        connector, ops = _connector()
        ops.read_records.return_value = [_record("11"), _record("22")]
        tickets = [
            _record("t1", associations={"contacts": _inline(["11", "22"])}),
            _record("t2", associations={"contacts": _inline(["22"])}),
        ]

        result = connector._linked_records(
            HubSpotObjectType.TICKETS, tickets, "contacts", strict=False
        )

        ops.read_associations.assert_not_called()
        # A contact linked to both tickets is read once.
        ops.read_records.assert_called_once()
        assert ops.read_records.call_args.kwargs["variant"] == "contacts"
        assert ops.read_records.call_args.kwargs["ids"] == ["11", "22"]
        assert {k: [r.id for r in v] for k, v in result.items()} == {
            "t1": ["11", "22"],
            "t2": ["22"],
        }

    def test_links_are_read_for_the_whole_batch_and_paged_per_record(self) -> None:
        connector, ops = _connector()
        ops.read_associations.side_effect = [
            {
                "t1": HubSpotPage(items=["1", "2"], next_after="c1"),
                "t2": HubSpotPage(items=["3"]),
            },
            {"t1": HubSpotPage(items=["2", "4"])},
        ]
        ops.read_records.return_value = [_record(i) for i in ["1", "2", "3", "4"]]
        tickets = [
            _record("t1", associations={"contacts": _inline(["1"], True)}),
            _record("t2"),
            _record("t3"),
        ]

        result = connector._linked_records(
            HubSpotObjectType.TICKETS, tickets, "contacts", strict=False
        )

        cursors = [c.kwargs["cursors"] for c in ops.read_associations.call_args_list]
        # Only the record with more links is asked for its next page.
        assert cursors == [{"t1": None, "t2": None, "t3": None}, {"t1": "c1"}]
        # One entry per association label, so the ids collapse in order.
        assert {k: [r.id for r in v] for k, v in result.items()} == {
            "t1": ["1", "2", "4"],
            "t2": ["3"],
            "t3": [],
        }

    def test_notes_are_always_read_through_v4(self) -> None:
        connector, ops = _connector()
        ops.read_associations.return_value = {"t1": HubSpotPage(items=["n1"])}
        ops.read_records.return_value = [_record("n1")]
        ticket = _record("t1", associations={"contacts": _inline(["11"])})

        result = connector._linked_records(
            HubSpotObjectType.TICKETS, [ticket], "notes", strict=False
        )

        assert ops.read_associations.call_args.kwargs["to_object_type"] == "notes"
        assert [r.id for r in result["t1"]] == ["n1"]

    def test_a_cursor_that_stops_moving_drops_the_links_of_the_batch(self) -> None:
        connector, ops = _connector()
        ops.read_associations.side_effect = [
            {"t1": HubSpotPage(items=["1"], next_after="c1")},
            {"t1": HubSpotPage(items=["1"], next_after="c1")},
        ]

        result = connector._linked_records(
            HubSpotObjectType.TICKETS, [_record("t1")], "contacts", strict=False
        )

        assert result == {}
        ops.read_records.assert_not_called()

    def test_a_failed_read_is_retried_once_then_dropped(self) -> None:
        connector, ops = _connector()
        ops.read_records.side_effect = RuntimeError("boom")
        ticket = _record("t1", associations={"contacts": _inline(["1"])})

        with patch("onyx.connectors.hubspot.connector.time.sleep"):
            result = connector._linked_records(
                HubSpotObjectType.TICKETS, [ticket], "contacts", strict=False
            )

        assert result == {"t1": []}
        assert ops.read_records.call_count == 2


def test_a_poll_reads_links_per_batch_not_per_record() -> None:
    """A search carries no links, so each linked type costs one link read and
    one record read per batch of a page of records."""
    connector, ops = _connector()
    connector.object_types = {"tickets"}
    tickets = [_record(f"t{i}", modified="2024-01-02T00:00:00Z") for i in range(150)]
    ops.search_records.side_effect = [
        HubSpotPage(items=tickets[:100], next_after="p2"),
        HubSpotPage(items=tickets[100:]),
    ]
    ops.read_associations.side_effect = lambda cursors, **_: {
        record_id: HubSpotPage(items=["9"]) for record_id in cursors
    }
    ops.read_records.side_effect = lambda ids, **_: [_record(i) for i in ids]

    documents = [
        document
        for batch in connector.poll_source(
            datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp(),
            datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp(),
        )
        for document in batch
    ]

    assert len(documents) == 150
    # Two batches times three linked types plus notes.
    assert ops.read_associations.call_count == 8
    assert ops.read_records.call_count == 8
    first = documents[0]
    assert isinstance(first, Document)
    assert first.metadata["associated_contact_ids"] == ["9"]
    # The record section, three linked records and one note.
    assert len(first.sections) == 5


class TestSearchTimeRange:
    START = datetime(2024, 1, 1, tzinfo=timezone.utc)
    END = datetime(2024, 2, 1, tzinfo=timezone.utc)

    def _search(self, connector: HubSpotConnector) -> list[HubSpotRecord]:
        return list(
            connector._search_time_range(
                HubSpotObjectType.TICKETS, ["prop"], self.START, self.END
            )
        )

    def test_passes_the_window_to_the_search(self) -> None:
        connector, ops = _connector()
        ops.search_records.return_value = HubSpotPage(items=[_record()])

        self._search(connector)

        ops.search_records.assert_called_once_with(
            variant=HubSpotObjectType.TICKETS,
            properties=["prop"],
            modified_after=self.START,
            modified_before=self.END,
            after=None,
        )

    def test_pages_until_no_cursor(self) -> None:
        connector, ops = _connector()
        ops.search_records.side_effect = [
            HubSpotPage(items=[_record("1"), _record("2")], next_after="c1"),
            HubSpotPage(items=[_record("3"), _record("4")]),
        ]

        results = self._search(connector)

        assert [r.id for r in results] == ["1", "2", "3", "4"]
        assert [c.kwargs["after"] for c in ops.search_records.call_args_list] == [
            None,
            "c1",
        ]

    def test_under_the_cap_yields_everything_once(self) -> None:
        connector, ops = _connector()
        records = [
            _record(str(i), modified="2024-01-15T00:00:00.000Z")
            for i in range(HUBSPOT_SEARCH_LIMIT - 1)
        ]
        ops.search_records.return_value = HubSpotPage(items=records)

        assert self._search(connector) == records
        ops.search_records.assert_called_once()

    def test_the_cap_continues_from_the_last_modified_timestamp(self) -> None:
        connector, ops = _connector()
        last_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        capped = [
            _record(str(i), modified=last_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            for i in range(HUBSPOT_SEARCH_LIMIT)
        ]
        continuation = _record("next", modified="2024-01-15T00:00:00.001Z")
        ops.search_records.side_effect = [
            HubSpotPage(items=capped),
            HubSpotPage(items=[continuation]),
        ]

        results = self._search(connector)

        assert len(results) == HUBSPOT_SEARCH_LIMIT + 1
        assert results[-1] == continuation
        assert [
            c.kwargs["modified_after"] for c in ops.search_records.call_args_list
        ] == [self.START, last_dt]


class TestValidateConnectorSettings:
    def test_a_rejected_token_fails_creation(self) -> None:
        connector, ops = _connector()
        connector._portal_id = None
        ops.get_portal_id.side_effect = HubSpotApiError("portal info", 401, None, "")

        with pytest.raises(CredentialInvalidError, match="portal info"):
            connector.validate_connector_settings()

    def test_an_outage_is_not_a_bad_token(self) -> None:
        connector, ops = _connector()
        connector._portal_id = None
        ops.get_portal_id.side_effect = HubSpotApiError("portal info", 503, None, "")

        with pytest.raises(UnexpectedValidationError):
            connector.validate_connector_settings()
