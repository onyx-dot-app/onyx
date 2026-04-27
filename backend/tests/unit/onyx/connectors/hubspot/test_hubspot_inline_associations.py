from __future__ import annotations

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

        mock_client.crm.contacts.basic_api.get_by_id.side_effect = [
            make_contact("11"),
            make_contact("22"),
        ]

        with patch.object(connector, "_paginated_results") as mock_paginated:
            result = connector._get_associated_objects(
                mock_client,
                object_id="ticket1",
                from_object_type="tickets",
                to_object_type="contacts",
                inline_association_ids=["11", "22"],
            )

        mock_paginated.assert_not_called()
        assert mock_client.crm.contacts.basic_api.get_by_id.call_count == 2
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
