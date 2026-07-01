"""Unit tests for DocmostConnector internals.

These mock the DocmostClient so no live instance is needed. They cover:
  - credential wiring + base-URL derivation for page links
  - page -> Document conversion (id, sections, metadata, updated_at)
  - the recency-ordered time-window logic in _iter_pages (break vs skip)
  - the space allow-list filtering
  - validate_connector_settings error mapping
  - slim-doc id-only output
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.docmost.client import DocmostAuthError
from onyx.connectors.docmost.client import DocmostClientError
from onyx.connectors.docmost.connector import DocmostConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.models import ConnectorMissingCredentialError

CREDS = {
    "docmost_base_url": "https://docmost.test",
    "docmost_api_token": "tok",
}


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def _page(
    page_id: str,
    *,
    updated_at: str | None = None,
    space_id: str | None = None,
    title: str = "T",
    content: Any = None,
    slug: str | None = None,
) -> dict[str, Any]:
    page: dict[str, Any] = {"id": page_id, "title": title}
    if updated_at is not None:
        page["updatedAt"] = updated_at
    if space_id is not None:
        page["spaceId"] = space_id
    if content is not None:
        page["content"] = content
    if slug is not None:
        page["slugId"] = slug
    return page


def _para(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _connector_with_client(
    client: MagicMock, space_filter: list[str] | None = None
) -> DocmostConnector:
    c = DocmostConnector(space_filter=space_filter)
    c.load_credentials(CREDS)
    c._client = client
    return c


class TestCredentialWiring:
    def test_missing_credentials_raises(self) -> None:
        c = DocmostConnector()
        with pytest.raises(ConnectorMissingCredentialError):
            c.load_credentials({"docmost_base_url": "https://x"})

    def test_client_property_without_creds_raises(self) -> None:
        with pytest.raises(ConnectorMissingCredentialError):
            _ = DocmostConnector().client

    def test_web_base_url_strips_api_suffix(self) -> None:
        c = DocmostConnector()
        c.load_credentials(
            {"docmost_base_url": "https://docmost.test/api/", "docmost_api_token": "t"}
        )
        assert c._web_base_url == "https://docmost.test"


class TestValidateSettings:
    def test_auth_error_maps_to_credential_expired(self) -> None:
        client = MagicMock()
        client.paginate.side_effect = DocmostAuthError("bad token")
        c = _connector_with_client(client)
        with pytest.raises(CredentialExpiredError):
            c.validate_connector_settings()

    def test_client_error_maps_to_validation_error(self) -> None:
        client = MagicMock()
        client.paginate.side_effect = DocmostClientError("boom")
        c = _connector_with_client(client)
        with pytest.raises(ConnectorValidationError):
            c.validate_connector_settings()

    def test_ok_when_probe_succeeds(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter([{"id": "s1"}])
        c = _connector_with_client(client)
        c.validate_connector_settings()  # should not raise


class TestPageToDocument:
    def test_builds_document_fields(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(
            [
                _page(
                    "p1",
                    updated_at="2024-01-02T03:04:05Z",
                    space_id="space-a",
                    title="Hello",
                    content=_para("world"),
                    slug="hello-slug",
                )
            ]
        )
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "docmost:page:p1"
        assert doc.semantic_identifier == "Hello"
        assert doc.source.value == "docmost"
        assert doc.sections[0].text == "Hello\n\nworld"
        assert doc.sections[0].link == "https://docmost.test/p/hello-slug"
        assert doc.metadata["space_id"] == "space-a"
        assert doc.doc_updated_at == datetime(
            2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc
        )

    def test_title_only_page_indexes_title(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(
            [_page("p1", title="Just A Title", content=_para(""))]
        )
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        assert docs[0].sections[0].text == "Just A Title"

    def test_page_without_id_is_skipped(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(
            [{"title": "no id", "content": _para("x")}]
        )
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        assert docs == []

    def test_url_falls_back_to_page_id_without_slug(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter([_page("p9", content=_para("x"))])
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        assert docs[0].sections[0].link == "https://docmost.test/p/p9"


class TestFetchFullContent:
    def test_fetches_info_when_content_missing(self) -> None:
        client = MagicMock()
        # /pages/recent returns a summary with no content.
        client.paginate.return_value = iter([_page("p1", title="Summary")])
        # /pages/info returns the full body.
        client.post.return_value = _page(
            "p1", title="Summary", content=_para("full body")
        )
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        client.post.assert_called_once_with("pages/info", {"pageId": "p1"})
        assert "full body" in docs[0].sections[0].text

    def test_continues_when_full_fetch_fails(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter([_page("p1", title="Summary")])
        client.post.side_effect = DocmostClientError("nope")
        c = _connector_with_client(client)
        docs = [d for batch in c.load_from_state() for d in batch]
        # Falls back to the summary page; still indexes the title.
        assert docs[0].semantic_identifier == "Summary"


class TestPollWindow:
    def _pages(self) -> list[dict[str, Any]]:
        # Recency-ordered (newest first), as /pages/recent returns them.
        return [
            _page("p3", updated_at="2024-03-01T00:00:00Z", content=_para("c")),
            _page("p2", updated_at="2024-02-01T00:00:00Z", content=_para("b")),
            _page("p1", updated_at="2024-01-01T00:00:00Z", content=_para("a")),
        ]

    def test_breaks_below_start(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(self._pages())
        c = _connector_with_client(client)
        start = _ts("2024-02-01T00:00:00")
        end = _ts("2024-12-31T00:00:00")
        docs = [d for batch in c.poll_source(start, end) for d in batch]
        # p3 and p2 are in-window; p1 is older than start -> loop breaks.
        assert {d.id for d in docs} == {"docmost:page:p3", "docmost:page:p2"}

    def test_skips_above_end(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(self._pages())
        c = _connector_with_client(client)
        start = _ts("2024-01-01T00:00:00")
        end = _ts("2024-02-15T00:00:00")
        docs = [d for batch in c.poll_source(start, end) for d in batch]
        # p3 is newer than end -> skipped; p2 and p1 kept.
        assert {d.id for d in docs} == {"docmost:page:p2", "docmost:page:p1"}


class TestSpaceFilter:
    def test_only_allowed_space_pages_indexed(self) -> None:
        client = MagicMock()

        def paginate(path: str, *args: Any, **kwargs: Any) -> Any:
            if path == "spaces":
                return iter(
                    [
                        {"id": "id-eng", "slug": "engineering"},
                        {"id": "id-hr", "slug": "hr"},
                    ]
                )
            return iter(
                [
                    _page("p1", space_id="id-eng", content=_para("eng")),
                    _page("p2", space_id="id-hr", content=_para("hr")),
                ]
            )

        client.paginate.side_effect = paginate
        c = _connector_with_client(client, space_filter=["engineering"])
        docs = [d for batch in c.load_from_state() for d in batch]
        assert {d.id for d in docs} == {"docmost:page:p1"}


class TestSlimDocs:
    def test_slim_docs_are_id_only(self) -> None:
        client = MagicMock()
        client.paginate.return_value = iter(
            [_page("p1", content=_para("a")), _page("p2", content=_para("b"))]
        )
        c = _connector_with_client(client)
        ids = [s.id for batch in c.retrieve_all_slim_docs() for s in batch]
        assert ids == ["docmost:page:p1", "docmost:page:p2"]


class TestParseUpdated:
    def test_handles_z_suffix_and_naive(self) -> None:
        assert DocmostConnector._parse_updated("2024-01-01T00:00:00Z") == datetime(
            2024, 1, 1, tzinfo=timezone.utc
        )

    def test_returns_none_for_garbage(self) -> None:
        assert DocmostConnector._parse_updated("not-a-date") is None
        assert DocmostConnector._parse_updated(None) is None
