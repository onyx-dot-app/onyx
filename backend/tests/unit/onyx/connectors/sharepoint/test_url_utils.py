"""Unit tests for SharePoint document GUID extraction."""

import base64
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from onyx.connectors.sharepoint.url_utils import extract_sharepoint_document_guid
from onyx.connectors.sharepoint.url_utils import sharepoint_page_url_variants

_GUID = "2AB3C4D5-6E7F-4A1B-9C0D-1E2F3A4B5C6D"
_SITE = "https://acme.sharepoint.com/sites/eng"


def _extract(url: str) -> str | None:
    split = urlsplit(url)
    return extract_sharepoint_document_guid(split.query, split.path)


def _make_sharing_token(guid: str, header: bytes = b"!\x00") -> str:
    """Build a sharing-link token: header + item GUID (little-endian) + opaque tail."""
    raw = header + UUID(guid).bytes_le + b"\x01" + bytes(16)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "url",
    [
        # percent-encoded braces (the shape SharePoint's UI produces)
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc=%7B{_GUID}%7D&file=Foo.docx&action=default",
        # raw braces
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc={{{_GUID}}}&file=Foo.docx",
        # no braces
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc={_GUID}",
        # lowercase GUID
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc=%7B{_GUID.lower()}%7D",
        # dash-less hex GUID
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc={_GUID.replace('-', '').lower()}",
        # different param order / extra params
        f"{_SITE}/_layouts/15/Doc.aspx?file=Foo.docx&mobileredirect=true&sourcedoc=%7B{_GUID}%7D",
        # WopiFrame variant
        f"{_SITE}/_layouts/15/WopiFrame.aspx?sourcedoc=%7B{_GUID}%7D&action=view",
        # /:w:/r/ redirect form of the Doc.aspx URL
        f"https://acme.sharepoint.com/:w:/r/sites/eng/_layouts/15/Doc.aspx"
        f"?sourcedoc=%7B{_GUID}%7D&file=Foo.docx&action=default&mobileredirect=true",
        # sharing link whose token embeds the GUID
        f"https://acme.sharepoint.com/:w:/s/eng/{_make_sharing_token(_GUID)}?e=u4Gcoi",
        # sharing link without the tracking param
        f"https://acme.sharepoint.com/:x:/s/eng/{_make_sharing_token(_GUID)}",
    ],
)
def test_extracts_canonical_guid(url: str) -> None:
    assert _extract(url) == _GUID


@pytest.mark.parametrize(
    "url",
    [
        # SitePages URL — no sourcedoc
        f"{_SITE}/SitePages/Team-Updates.aspx",
        # sharing token from an unsupported family (not the "!\x00" layout)
        f"https://acme.sharepoint.com/:w:/s/eng/{_make_sharing_token(_GUID, header=bytes(2))}",
        # E...-family sharing token — layout unverified, deliberately punted
        "https://acme.sharepoint.com/:w:/s/eng/EZx1y2z3AbCdEfGhIjKlMnOp",
        # sourcedoc present but not a valid GUID
        f"{_SITE}/_layouts/15/Doc.aspx?sourcedoc=%7Bnot-a-guid%7D",
        # no query string at all
        f"{_SITE}/Shared%20Documents/Foo.docx",
        "",
    ],
)
def test_returns_none_without_valid_guid(url: str) -> None:
    assert _extract(url) is None


def test_page_url_variants_strip_query_fragment_and_slash() -> None:
    url = f"{_SITE}/SitePages/Team-Updates.aspx?web=1#section"
    assert sharepoint_page_url_variants(url) == [
        url,
        f"{_SITE}/SitePages/Team-Updates.aspx",
    ]


def test_page_url_variants_dedupe_when_already_canonical() -> None:
    url = f"{_SITE}/SitePages/Team-Updates.aspx"
    assert sharepoint_page_url_variants(url) == [url]
