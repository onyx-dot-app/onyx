from typing import Any
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.clickup_docs.connector import ClickupDocsConnector


def _mock_response(json_response: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_response
    return response


def _connector() -> ClickupDocsConnector:
    connector = ClickupDocsConnector()
    connector.load_credentials(
        {"clickup_api_token": "test-token", "clickup_team_id": "ws1"}
    )
    return connector


def _route(url: str, **_kwargs: Any) -> MagicMock:
    if url.endswith("/docs"):
        return _mock_response(
            {"docs": [{"id": "d1", "name": "Runbooks"}], "next_cursor": None}
        )
    if url.endswith("/docs/d1"):
        return _mock_response({"id": "d1", "name": "Runbooks"})
    if url.endswith("/pages"):
        # Nested tree: a section page with real, no-access and empty child pages.
        return _mock_response(
            [
                {
                    "id": "p0",
                    "name": "Section",
                    "content": "",
                    "pages": [
                        {
                            "id": "p1",
                            "name": "Real page",
                            "content": "# Title\nbody",
                            "date_created": 1700000000000,
                            "date_updated": 1700000100000,
                        },
                        {
                            "id": "p2",
                            "name": "Hidden",
                            "content": "You do not have access to this Doc",
                        },
                    ],
                }
            ]
        )
    raise AssertionError(f"unexpected url {url}")


def test_load_from_state_maps_pages_and_skips_empty_and_no_access() -> None:
    connector = _connector()
    with patch(
        "onyx.connectors.clickup_docs.connector.requests.get", side_effect=_route
    ):
        batches = list(connector.load_from_state())

    docs = [d for batch in batches for d in batch]
    # Only the single real-content page survives (empty + no-access skipped).
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "clickup_doc__d1__p1"
    assert doc.source == DocumentSource.CLICKUP_DOCS
    assert doc.semantic_identifier == "Runbooks / Real page"
    assert doc.sections[0].text == "# Title\nbody"
    assert doc.sections[0].link == "https://app.clickup.com/ws1/v/dc/d1/p1"
    assert doc.metadata["doc_id"] == "d1"
    assert doc.metadata["page_id"] == "p1"


def test_list_docs_scopes_by_parent_type() -> None:
    connector = ClickupDocsConnector(connector_type="space", connector_ids=["s1"])
    connector.load_credentials(
        {"clickup_api_token": "test-token", "clickup_team_id": "ws1"}
    )
    with patch(
        "onyx.connectors.clickup_docs.connector.requests.get", side_effect=_route
    ) as mock_get:
        list(connector.load_from_state())

    docs_call = next(
        c for c in mock_get.call_args_list if c.args[0].endswith("/docs")
    )
    assert docs_call.kwargs["params"]["parent_type"] == "SPACE"
    assert docs_call.kwargs["params"]["parent_id"] == "s1"


def test_doc_scope_indexes_single_doc_without_listing() -> None:
    connector = ClickupDocsConnector(connector_type="doc", connector_ids=["d1"])
    connector.load_credentials(
        {"clickup_api_token": "test-token", "clickup_team_id": "ws1"}
    )
    with patch(
        "onyx.connectors.clickup_docs.connector.requests.get", side_effect=_route
    ) as mock_get:
        docs = [d for batch in connector.load_from_state() for d in batch]

    # "doc" scope resolves the Doc directly and never calls the listing endpoint.
    assert len(docs) == 1
    assert docs[0].id == "clickup_doc__d1__p1"
    assert not any(c.args[0].endswith("/docs") for c in mock_get.call_args_list)
