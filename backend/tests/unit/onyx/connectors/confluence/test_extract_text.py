from unittest import mock

from onyx.connectors.confluence.onyx_confluence import extract_text_from_confluence_html


def _make_confluence_object(html: str) -> dict:
    return {"body": {"storage": {"value": html}}}


def _make_mock_client() -> mock.Mock:
    client = mock.Mock()
    client.paginated_cql_retrieval.return_value = iter([])
    return client


def test_date_lozenge_text_is_preserved() -> None:
    """Text inside a /Date macro span must appear in the extracted output."""
    html = (
        "<p>Meeting on "
        '<span class="date-lozenger-container">April 22, 2026</span>'
        " at noon.</p>"
    )
    result = extract_text_from_confluence_html(
        confluence_client=_make_mock_client(),
        confluence_object=_make_confluence_object(html),
        fetched_titles=set(),
    )
    assert "April 22, 2026" in result


def test_page_without_date_lozenge_unaffected() -> None:
    """Pages with no date lozenge spans are processed normally."""
    html = "<p>No dates here.</p>"
    result = extract_text_from_confluence_html(
        confluence_client=_make_mock_client(),
        confluence_object=_make_confluence_object(html),
        fetched_titles=set(),
    )
    assert "No dates here." in result
