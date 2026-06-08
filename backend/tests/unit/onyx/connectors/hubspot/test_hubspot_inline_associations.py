from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.hubspot.connector import HubSpotConnector


def _make_connector() -> HubSpotConnector:
    c = HubSpotConnector()
    c._access_token = "token"
    c._portal_id = "portal"
    return c


def _make_assoc_collection(ids: list[str], has_next: bool = False) -> MagicMock:
    """Build a mock CollectionResponseAssociatedId."""
    results = [MagicMock(id=id_) for id_ in ids]
    paging = MagicMock()
    paging.next = MagicMock() if has_next else None
    collection = MagicMock()
    collection.results = results
    collection.paging = paging
    return collection


class TestExtractInlineAssociationIds:
    def test_returns_ids_when_no_overflow(self) -> None:
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = {"contacts": _make_assoc_collection(["1", "2", "3"])}

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result == ["1", "2", "3"]

    def test_returns_empty_list_when_type_not_present(self) -> None:
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = {"companies": _make_assoc_collection(["5"])}

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result == []

    def test_returns_none_when_associations_is_none(self) -> None:
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = None

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result is None

    def test_returns_none_when_associations_is_not_a_dict(self) -> None:
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = MagicMock()  # truthy non-dict

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result is None

    def test_returns_none_on_overflow(self) -> None:
        """When paging.next is set the inline data is truncated; caller must fall back to v4 API."""
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = {
            "contacts": _make_assoc_collection(["1", "2"], has_next=True)
        }

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result is None


class TestGetAssociatedObjectsSkipsV4Call:
    def test_inline_ids_drive_object_fetch_and_skip_v4(self) -> None:
        """Inline IDs are used to fetch objects; the v4 association lookup is never called."""
        connector = _make_connector()
        mock_client = MagicMock()

        def make_contact(id_: str) -> MagicMock:
            m = MagicMock()
            m.to_dict.return_value = {"id": id_, "properties": {"firstname": "A"}}
            return m

        batch_response = MagicMock()
        batch_response.results = [make_contact("11"), make_contact("22")]
        mock_client.crm.contacts.batch_api.read.return_value = batch_response

        with patch.object(connector, "_paginated_results") as mock_paginated:
            result = connector._get_associated_objects(
                mock_client,
                object_id="ticket1",
                from_object_type="tickets",
                to_object_type="contacts",
                inline_association_ids=["11", "22"],
            )

        mock_paginated.assert_not_called()
        assert mock_client.crm.contacts.batch_api.read.call_count == 1
        assert [r["id"] for r in result] == ["11", "22"]

    def test_v4_api_called_when_inline_ids_is_none(self) -> None:
        """None signals overflow — connector falls back to the v4 associations API."""
        connector = _make_connector()
        mock_client = MagicMock()

        with patch.object(
            connector, "_paginated_results", return_value=iter([])
        ) as mock_paginated:
            connector._get_associated_objects(
                mock_client,
                object_id="obj1",
                from_object_type="tickets",
                to_object_type="contacts",
                inline_association_ids=None,
            )

        mock_paginated.assert_called_once()


class TestExtractInlineAssociationIdsDedup:
    def test_deduplicates_ids_from_multiple_labels(self) -> None:
        """HubSpot returns one entry per association label; duplicates must be collapsed."""
        connector = _make_connector()
        obj = MagicMock()
        # Simulate HubSpot returning the same IDs twice (two labels each)
        obj.associations = {
            "contacts": _make_assoc_collection(["1", "2", "3", "1", "2", "3"])
        }

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result == ["1", "2", "3"]

    def test_preserves_order_after_dedup(self) -> None:
        connector = _make_connector()
        obj = MagicMock()
        obj.associations = {
            "contacts": _make_assoc_collection(["3", "1", "2", "3", "1", "2"])
        }

        result = connector._extract_inline_association_ids(obj, "contacts")

        assert result == ["3", "1", "2"]


class TestBuildTimeFilterGroup:
    def test_both_start_and_end(self) -> None:
        connector = _make_connector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        group = connector._build_time_filter_group(start, end, "hs_lastmodifieddate")

        assert len(group.filters) == 2
        operators = {f.operator for f in group.filters}
        assert operators == {"GTE", "LTE"}
        values = {f.value for f in group.filters}
        assert str(int(start.timestamp() * 1000)) in values
        assert str(int(end.timestamp() * 1000)) in values

    def test_start_only(self) -> None:
        connector = _make_connector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

        group = connector._build_time_filter_group(start, None, "hs_lastmodifieddate")

        assert len(group.filters) == 1
        assert group.filters[0].operator == "GTE"
        assert group.filters[0].value == str(int(start.timestamp() * 1000))

    def test_end_only(self) -> None:
        connector = _make_connector()
        end = datetime(2024, 6, 1, tzinfo=timezone.utc)

        group = connector._build_time_filter_group(None, end, "lastmodifieddate")

        assert len(group.filters) == 1
        assert group.filters[0].operator == "LTE"
        assert group.filters[0].property_name == "lastmodifieddate"

    def test_property_name_is_passed_through(self) -> None:
        connector = _make_connector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

        group = connector._build_time_filter_group(start, None, "lastmodifieddate")

        assert group.filters[0].property_name == "lastmodifieddate"


class TestSearchPaginatedResults:
    def _make_page(self, ids: list[str], next_after: str | None) -> MagicMock:
        page = MagicMock()
        page.results = [MagicMock(id=i) for i in ids]
        if next_after is not None:
            page.paging = MagicMock()
            page.paging.next = MagicMock()
            page.paging.next.after = next_after
        else:
            page.paging = None
        return page

    def test_single_page(self) -> None:
        connector = _make_connector()
        search_fn = MagicMock(return_value=self._make_page(["1", "2"], None))
        filter_group = MagicMock()

        with patch.object(
            connector, "_call_hubspot", side_effect=lambda fn, **kw: fn(**kw)
        ):
            results = list(
                connector._search_paginated_results(search_fn, ["prop"], filter_group)
            )

        assert len(results) == 2
        assert search_fn.call_count == 1

    def test_large_single_page(self) -> None:
        from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT

        connector = _make_connector()
        # Return one giant page that exactly hits the limit
        big_page = self._make_page(
            [str(i) for i in range(HUBSPOT_SEARCH_LIMIT)], next_after=None
        )
        search_fn = MagicMock(return_value=big_page)
        filter_group = MagicMock()

        with patch.object(
            connector, "_call_hubspot", side_effect=lambda fn, **kw: fn(**kw)
        ):
            results = list(
                connector._search_paginated_results(search_fn, ["prop"], filter_group)
            )

        assert len(results) == HUBSPOT_SEARCH_LIMIT

    def test_multiple_pages(self) -> None:
        connector = _make_connector()
        pages = [
            self._make_page(["1", "2"], next_after="cursor1"),
            self._make_page(["3", "4"], next_after=None),
        ]
        search_fn = MagicMock(side_effect=pages)
        filter_group = MagicMock()

        with patch.object(
            connector, "_call_hubspot", side_effect=lambda fn, **kw: fn(**kw)
        ):
            results = list(
                connector._search_paginated_results(search_fn, ["prop"], filter_group)
            )

        assert len(results) == 4
        assert search_fn.call_count == 2
        # Second call must pass the cursor from the first page
        second_call_request = search_fn.call_args_list[1][1][
            "public_object_search_request"
        ]
        assert second_call_request.after == "cursor1"


class TestSearchWithTimeSplit:
    def _make_result(self, ts_iso: str, prop: str = "hs_lastmodifieddate") -> MagicMock:
        r = MagicMock()
        r.properties = {prop: ts_iso}
        return r

    def test_yields_all_when_under_limit(self) -> None:
        from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT

        connector = _make_connector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)
        items = [
            self._make_result("2024-01-15T00:00:00.000Z")
            for _ in range(HUBSPOT_SEARCH_LIMIT - 1)
        ]

        with patch.object(
            connector, "_search_paginated_results", return_value=iter(items)
        ):
            results = list(
                connector._search_time_range(
                    MagicMock(), ["prop"], start, end, "hs_lastmodifieddate"
                )
            )

        assert results == items

    def test_yields_fetched_and_continues_from_last_timestamp(self) -> None:
        from onyx.connectors.hubspot.connector import HUBSPOT_SEARCH_LIMIT

        connector = _make_connector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)

        # Last item has a timestamp clearly after start (ISO 8601 format, as HubSpot returns)
        last_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        last_ts_iso = last_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        first_batch = [self._make_result(last_ts_iso)] * HUBSPOT_SEARCH_LIMIT
        continuation = [self._make_result("2024-01-15T00:00:00.001Z")]

        search_calls: list[tuple[datetime, datetime]] = []
        original = connector._search_time_range

        def fake_split(fn: Any, props: Any, s: datetime, e: datetime, prop: Any) -> Any:
            search_calls.append((s, e))
            if s == start:
                return original(fn, props, s, e, prop)
            return iter(continuation)

        with patch.object(
            connector, "_search_paginated_results", return_value=iter(first_batch)
        ):
            with patch.object(connector, "_search_time_range", side_effect=fake_split):
                results = list(
                    fake_split(MagicMock(), ["prop"], start, end, "hs_lastmodifieddate")
                )

        # All 10k fetched results are yielded, then the continuation
        assert len(results) == HUBSPOT_SEARCH_LIMIT + len(continuation)
        assert results[-1] is continuation[0]
        # Second call starts from last_ts_ms
        assert len(search_calls) == 2
        assert search_calls[1][0] == last_dt
