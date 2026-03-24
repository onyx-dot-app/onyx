"""Unit tests for Notion connector data source API migration.

Tests the new data source discovery + querying flow and the
data_source_id -> database_id parent resolution.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.connector import NotionPage


def _make_connector() -> NotionConnector:
    connector = NotionConnector()
    connector.load_credentials({"notion_integration_token": "fake-token"})
    return connector


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestFetchDataSourcesForDatabase:
    def test_multi_source_database(self) -> None:
        connector = _make_connector()
        resp = _mock_response(
            {
                "object": "database",
                "id": "db-1",
                "data_sources": [
                    {"id": "ds-1", "name": "Source A"},
                    {"id": "ds-2", "name": "Source B"},
                ],
            }
        )
        with patch(
            "onyx.connectors.notion.connector.rl_requests.get", return_value=resp
        ):
            result = connector._fetch_data_sources_for_database("db-1")

        assert result == [("ds-1", "Source A"), ("ds-2", "Source B")]

    def test_single_source_database(self) -> None:
        connector = _make_connector()
        resp = _mock_response(
            {
                "object": "database",
                "id": "db-1",
                "data_sources": [{"id": "ds-1", "name": "Only Source"}],
            }
        )
        with patch(
            "onyx.connectors.notion.connector.rl_requests.get", return_value=resp
        ):
            result = connector._fetch_data_sources_for_database("db-1")

        assert result == [("ds-1", "Only Source")]

    def test_404_returns_empty(self) -> None:
        connector = _make_connector()
        resp = _mock_response({"object": "error"}, status_code=404)
        with patch(
            "onyx.connectors.notion.connector.rl_requests.get", return_value=resp
        ):
            result = connector._fetch_data_sources_for_database("db-missing")

        assert result == []


class TestFetchDataSource:
    def test_query_returns_pages(self) -> None:
        connector = _make_connector()
        resp = _mock_response(
            {
                "results": [
                    {
                        "object": "page",
                        "id": "page-1",
                        "properties": {"Name": {"type": "title", "title": []}},
                    }
                ],
                "next_cursor": None,
            }
        )
        with patch(
            "onyx.connectors.notion.connector.rl_requests.post", return_value=resp
        ):
            result = connector._fetch_data_source("ds-1")

        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "page-1"
        assert result["next_cursor"] is None

    def test_404_returns_empty_results(self) -> None:
        connector = _make_connector()
        resp = _mock_response({"object": "error"}, status_code=404)
        with patch(
            "onyx.connectors.notion.connector.rl_requests.post", return_value=resp
        ):
            result = connector._fetch_data_source("ds-missing")

        assert result == {"results": [], "next_cursor": None}


class TestGetParentRawId:
    def test_database_id_parent(self) -> None:
        connector = _make_connector()
        parent = {"type": "database_id", "database_id": "db-1"}
        assert connector._get_parent_raw_id(parent) == "db-1"

    def test_data_source_id_with_mapping(self) -> None:
        connector = _make_connector()
        connector._data_source_to_database_map["ds-1"] = "db-1"
        parent = {"type": "data_source_id", "data_source_id": "ds-1"}
        assert connector._get_parent_raw_id(parent) == "db-1"

    def test_data_source_id_without_mapping_falls_back(self) -> None:
        connector = _make_connector()
        parent = {"type": "data_source_id", "data_source_id": "ds-unknown"}
        assert connector._get_parent_raw_id(parent) == "ds-unknown"

    def test_workspace_parent(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        parent = {"type": "workspace"}
        assert connector._get_parent_raw_id(parent) == "ws-1"

    def test_page_id_parent(self) -> None:
        connector = _make_connector()
        parent = {"type": "page_id", "page_id": "page-1"}
        assert connector._get_parent_raw_id(parent) == "page-1"

    def test_none_parent_defaults_to_workspace(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        assert connector._get_parent_raw_id(None) == "ws-1"


class TestReadPagesFromDatabaseMultiSource:
    def test_queries_all_data_sources(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"

        with (
            patch.object(
                connector,
                "_fetch_data_sources_for_database",
                return_value=[("ds-1", "Source A"), ("ds-2", "Source B")],
            ),
            patch.object(
                connector,
                "_fetch_data_source",
                return_value={"results": [], "next_cursor": None},
            ) as mock_fetch_ds,
        ):
            result = connector._read_pages_from_database("db-1")

        assert mock_fetch_ds.call_count == 2
        mock_fetch_ds.assert_any_call("ds-1", None)
        mock_fetch_ds.assert_any_call("ds-2", None)

        assert connector._data_source_to_database_map["ds-1"] == "db-1"
        assert connector._data_source_to_database_map["ds-2"] == "db-1"

        assert result.blocks == []
        assert result.child_page_ids == []

    def test_collects_pages_from_all_sources(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        connector.recursive_index_enabled = True

        ds1_results = {
            "results": [{"object": "page", "id": "page-from-ds1", "properties": {}}],
            "next_cursor": None,
        }
        ds2_results = {
            "results": [{"object": "page", "id": "page-from-ds2", "properties": {}}],
            "next_cursor": None,
        }

        with (
            patch.object(
                connector,
                "_fetch_data_sources_for_database",
                return_value=[("ds-1", "Source A"), ("ds-2", "Source B")],
            ),
            patch.object(
                connector,
                "_fetch_data_source",
                side_effect=[ds1_results, ds2_results],
            ),
        ):
            result = connector._read_pages_from_database("db-1")

        assert "page-from-ds1" in result.child_page_ids
        assert "page-from-ds2" in result.child_page_ids


class TestInTrashField:
    def test_notion_page_accepts_in_trash(self) -> None:
        page = NotionPage(
            id="page-1",
            created_time="2026-01-01T00:00:00.000Z",
            last_edited_time="2026-01-01T00:00:00.000Z",
            in_trash=False,
            properties={},
            url="https://notion.so/page-1",
        )
        assert page.in_trash is False

    def test_notion_page_in_trash_true(self) -> None:
        page = NotionPage(
            id="page-1",
            created_time="2026-01-01T00:00:00.000Z",
            last_edited_time="2026-01-01T00:00:00.000Z",
            in_trash=True,
            properties={},
            url="https://notion.so/page-1",
        )
        assert page.in_trash is True


class TestFetchDatabaseAsPage:
    def test_handles_missing_properties(self) -> None:
        connector = _make_connector()
        resp = _mock_response(
            {
                "object": "database",
                "id": "db-1",
                "created_time": "2026-01-01T00:00:00.000Z",
                "last_edited_time": "2026-01-01T00:00:00.000Z",
                "in_trash": False,
                "url": "https://notion.so/db-1",
                "title": [{"text": {"content": "My DB"}, "plain_text": "My DB"}],
                "data_sources": [{"id": "ds-1", "name": "Source"}],
            }
        )
        with patch(
            "onyx.connectors.notion.connector.rl_requests.get", return_value=resp
        ):
            page = connector._fetch_database_as_page("db-1")

        assert page.id == "db-1"
        assert page.database_name == "My DB"
        assert page.properties == {}
