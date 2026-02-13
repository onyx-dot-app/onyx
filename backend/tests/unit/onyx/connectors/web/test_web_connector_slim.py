from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import SlimDocument
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector


def _collect_slim_docs(connector: WebConnector) -> list[SlimDocument]:
    """Helper to flatten all batches into a single list."""
    return [doc for batch in connector.retrieve_all_slim_docs() for doc in batch]


def test_web_connector_is_slim_connector() -> None:
    connector = WebConnector(
        base_url="https://example.com",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )
    assert isinstance(connector, SlimConnector)


def test_slim_single_mode() -> None:
    connector = WebConnector(
        base_url="https://example.com/page",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )
    docs = _collect_slim_docs(connector)
    assert len(docs) == 1
    assert docs[0].id == "https://example.com/page"


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_slim_sitemap_mode(mock_extract: MagicMock) -> None:
    mock_extract.return_value = [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    connector = WebConnector(
        base_url="https://example.com/sitemap.xml",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
    )
    # Override to_visit_list since __init__ calls extract_urls_from_sitemap too
    docs = _collect_slim_docs(connector)
    assert len(docs) == 3
    assert {d.id for d in docs} == {
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    }


def test_slim_upload_mode() -> None:
    connector = WebConnector.__new__(WebConnector)
    connector.web_connector_type = WEB_CONNECTOR_VALID_SETTINGS.UPLOAD.value
    connector.to_visit_list = [
        "https://example.com/1",
        "https://example.com/2",
    ]
    connector.batch_size = 100
    docs = _collect_slim_docs(connector)
    assert len(docs) == 2
    assert docs[0].id == "https://example.com/1"
    assert docs[1].id == "https://example.com/2"


@patch("onyx.connectors.web.connector.protected_url_check")
@patch("onyx.connectors.web.connector.requests.get")
def test_slim_recursive_discovers_links(
    mock_get: MagicMock, mock_url_check: MagicMock
) -> None:
    """Recursive mode should discover internal links via lightweight HTTP."""
    page_a_html = """
    <html><body>
        <a href="https://example.com/b">Link B</a>
        <a href="https://example.com/c">Link C</a>
        <a href="https://other.com/external">External</a>
    </body></html>
    """
    page_b_html = "<html><body><p>Page B</p></body></html>"
    page_c_html = """
    <html><body>
        <a href="https://example.com/a">Back to A</a>
    </body></html>
    """

    def fake_get(url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        pages = {
            "https://example.com/a": page_a_html,
            "https://example.com/b": page_b_html,
            "https://example.com/c": page_c_html,
        }
        resp = MagicMock()
        resp.content = pages.get(url, "<html></html>").encode()
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        return resp

    mock_get.side_effect = fake_get
    mock_url_check.return_value = None

    connector = WebConnector(
        base_url="https://example.com/a",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    )
    docs = _collect_slim_docs(connector)
    discovered_ids = {d.id for d in docs}
    assert "https://example.com/a" in discovered_ids
    assert "https://example.com/b" in discovered_ids
    assert "https://example.com/c" in discovered_ids
    # External link should NOT be included
    assert "https://other.com/external" not in discovered_ids


@patch("onyx.connectors.web.connector.protected_url_check")
@patch("onyx.connectors.web.connector.requests.get")
def test_slim_recursive_includes_non_html(
    mock_get: MagicMock, mock_url_check: MagicMock
) -> None:
    """Non-HTML resources (e.g. PDFs) should be included as documents."""
    page_html = """
    <html><body>
        <a href="https://example.com/doc.pdf">PDF</a>
    </body></html>
    """

    def fake_get(url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        resp = MagicMock()
        if url.endswith(".pdf"):
            resp.content = b"%PDF-1.4 ..."
            resp.headers = {"content-type": "application/pdf"}
        else:
            resp.content = page_html.encode()
            resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        return resp

    mock_get.side_effect = fake_get
    mock_url_check.return_value = None

    connector = WebConnector(
        base_url="https://example.com/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    )
    docs = _collect_slim_docs(connector)
    discovered_ids = {d.id for d in docs}
    assert "https://example.com/" in discovered_ids
    assert "https://example.com/doc.pdf" in discovered_ids


@patch("onyx.connectors.web.connector.protected_url_check")
@patch("onyx.connectors.web.connector.requests.get")
def test_slim_recursive_skips_failed_urls(
    mock_get: MagicMock, mock_url_check: MagicMock
) -> None:
    """URLs that fail to fetch should be skipped, not crash the crawl."""
    page_html = """
    <html><body>
        <a href="https://example.com/broken">Broken</a>
        <a href="https://example.com/ok">OK</a>
    </body></html>
    """

    def fake_get(url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        if "broken" in url:
            raise ConnectionError("Connection refused")
        resp = MagicMock()
        resp.content = page_html.encode() if url.endswith("/") else b"<html></html>"
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        return resp

    mock_get.side_effect = fake_get
    mock_url_check.return_value = None

    connector = WebConnector(
        base_url="https://example.com/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    )
    docs = _collect_slim_docs(connector)
    discovered_ids = {d.id for d in docs}
    assert "https://example.com/" in discovered_ids
    assert "https://example.com/ok" in discovered_ids
    assert "https://example.com/broken" not in discovered_ids


@patch("onyx.connectors.web.connector.protected_url_check")
@patch("onyx.connectors.web.connector.requests.get")
def test_slim_recursive_batching(
    mock_get: MagicMock, mock_url_check: MagicMock
) -> None:
    """Results should be yielded in batches of batch_size."""
    # Create a page with many links
    links = "".join(f'<a href="https://example.com/page{i}">P{i}</a>' for i in range(5))
    root_html = f"<html><body>{links}</body></html>"

    def fake_get(url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        resp = MagicMock()
        resp.content = (
            root_html.encode()
            if "example.com/" == url.split("//")[1] + "/"
            else b"<html></html>"
        )
        resp.headers = {"content-type": "text/html"}
        resp.raise_for_status = MagicMock()
        return resp

    mock_get.side_effect = fake_get
    mock_url_check.return_value = None

    connector = WebConnector(
        base_url="https://example.com/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
        batch_size=2,
    )
    batches = list(connector.retrieve_all_slim_docs())
    # With 6 total pages (root + 5 links) and batch_size=2, expect 3 batches
    assert all(len(batch) <= 2 for batch in batches)
    total_docs = sum(len(b) for b in batches)
    assert total_docs == 6


def test_slim_empty_to_visit_list() -> None:
    """Empty to_visit_list should yield nothing."""
    connector = WebConnector.__new__(WebConnector)
    connector.to_visit_list = []
    connector.web_connector_type = WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value
    connector.batch_size = 100
    docs = _collect_slim_docs(connector)
    assert len(docs) == 0
