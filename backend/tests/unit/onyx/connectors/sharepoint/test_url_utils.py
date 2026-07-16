"""Unit tests for SharePoint document GUID extraction."""

from urllib.parse import urlsplit

import pytest

from onyx.connectors.sharepoint.url_utils import extract_sharepoint_document_guid
from onyx.connectors.sharepoint.url_utils import (
    sharepoint_drive_hash_from_drive_item_id,
)
from onyx.connectors.sharepoint.url_utils import sharepoint_drive_item_id_candidates
from onyx.connectors.sharepoint.url_utils import sharepoint_drive_item_id_from_guid
from onyx.connectors.sharepoint.url_utils import sharepoint_guid_from_drive_item_id
from onyx.connectors.sharepoint.url_utils import sharepoint_page_url_variants
from tests.utils.sharepoint import make_drive_item_id
from tests.utils.sharepoint import make_sharing_token as _make_sharing_token

_GUID = "2AB3C4D5-6E7F-4A1B-9C0D-1E2F3A4B5C6D"
_SITE = "https://acme.sharepoint.com/sites/eng"


def _extract(url: str) -> str | None:
    split = urlsplit(url)
    return extract_sharepoint_document_guid(split.query, split.path)


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
        # share-redirect URL: same token, carried in a `share=` query param
        f"{_SITE}/SitePages/Team-Updates.aspx"
        f"?csf=1&web=1&share={_make_sharing_token(_GUID)}&e=9xtHB2",
        # /:u:/r/ redirect form with the share token
        f"https://acme.sharepoint.com/:u:/r/sites/eng/SitePages/Team-Updates.aspx"
        f"?share={_make_sharing_token(_GUID)}",
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
        # E...-family token in a share= param punts the same way
        f"{_SITE}/SitePages/Team-Updates.aspx?share=EZx1y2z3AbCdEfGhIjKlMnOp",
        # share= value that isn't a token at all
        f"{_SITE}/SitePages/Team-Updates.aspx?share=not-a-token",
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


def test_page_url_variants_decode_clipboard_encoding() -> None:
    """A browser may percent-encode chars Graph webUrl stores raw (e.g. `'`)."""
    pasted = f"{_SITE}/SitePages/What%27s-happening.aspx"
    assert f"{_SITE}/SitePages/What's-happening.aspx" in sharepoint_page_url_variants(
        pasted
    )


def test_page_url_variants_requote_decoded_spaces() -> None:
    """Graph webUrl encodes spaces as %20; a pasted URL may have them decoded."""
    pasted = f"{_SITE}/Shared Documents/Foo (2022).pdf"
    variants = sharepoint_page_url_variants(pasted)
    assert f"{_SITE}/Shared%20Documents/Foo%20(2022).pdf" in variants
    # mixed case: encoded spaces but also an encoded sub-delim Graph keeps raw
    mixed = f"{_SITE}/Shared%20Documents/Foo%20%282022%29.pdf"
    assert f"{_SITE}/Shared%20Documents/Foo%20(2022).pdf" in (
        sharepoint_page_url_variants(mixed)
    )


# real (prefix, sourcedoc GUID, drive-item id) triples from live Graph data
_REAL_TRIPLES = [
    (
        "01RWUU3P",
        "0320E240-B69F-4D8D-A196-89674CD60485",
        "01RWUU3PKA4IQAHH5WRVG2DFUJM5GNMBEF",
    ),
    (
        "014NAK7T",
        "0EFE1B85-688F-4CBE-B9B7-1B8215F3A796",
        "014NAK7T4FDP7A5D3IXZGLTNY3QIK7HJ4W",
    ),
    (
        "016GMXOK",
        "054F6393-FA7A-4996-9188-6756BBC23BE2",
        "016GMXOKETMNHQK6X2SZEZDCDHK254EO7C",
    ),
]


@pytest.mark.parametrize("prefix,guid,expected_id", _REAL_TRIPLES)
def test_drive_item_id_candidates_reconstruct_real_ids(
    prefix: str, guid: str, expected_id: str
) -> None:
    candidates = sharepoint_drive_item_id_candidates(guid, [prefix])
    assert len(candidates) == 4  # 2 unresolved drive-hash bits
    assert expected_id in candidates
    assert all(c.startswith(prefix) for c in candidates)


def test_drive_item_id_candidates_roundtrip_synthetic_id() -> None:
    guid = "2AB3C4D5-6E7F-4A1B-9C0D-1E2F3A4B5C6D"
    doc_id = make_drive_item_id(guid)
    assert doc_id in sharepoint_drive_item_id_candidates(guid, [doc_id[:8]])


def test_drive_item_id_candidates_skip_invalid_prefixes() -> None:
    assert (
        sharepoint_drive_item_id_candidates(
            _GUID,
            # non-base32 chars / wrong shape / wrong length — e.g. other connectors' ids
            ["01SFDIZ0", "https://", "01AB", "02RWUU3P", ""],
        )
        == []
    )


def test_drive_item_id_candidates_invalid_guid() -> None:
    assert sharepoint_drive_item_id_candidates("not-a-guid", ["01RWUU3P"]) == []


@pytest.mark.parametrize("_prefix,guid,drive_item_id", _REAL_TRIPLES)
def test_guid_decodes_from_real_drive_item_ids(
    _prefix: str, guid: str, drive_item_id: str
) -> None:
    assert sharepoint_guid_from_drive_item_id(drive_item_id) == guid.lower()


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "not-a-drive-item-id",
        "02" + "A" * 32,  # wrong prefix
        "01" + "A" * 31,  # wrong length
        "01" + "a" * 32,  # lowercase — not Graph's base32 alphabet
        "01" + "1" * 32,  # '1' is outside the base32 alphabet
        "2ab3c4d5-6e7f-4a1b-9c0d-1e2f3a4b5c6d",  # already a GUID
    ],
)
def test_guid_decode_rejects_malformed_ids(bad_id: str) -> None:
    assert sharepoint_guid_from_drive_item_id(bad_id) is None
    assert sharepoint_drive_hash_from_drive_item_id(bad_id) is None


@pytest.mark.parametrize("_prefix,guid,drive_item_id", _REAL_TRIPLES)
def test_drive_item_id_reconstructs_from_hash_and_guid(
    _prefix: str, guid: str, drive_item_id: str
) -> None:
    """Any item id from a drive (e.g. its root folder's) carries the drive hash
    needed to reconstruct the exact id of any other item from its GUID."""
    drive_hash = sharepoint_drive_hash_from_drive_item_id(drive_item_id)
    assert drive_hash is not None
    assert sharepoint_drive_item_id_from_guid(drive_hash, guid) == drive_item_id


def test_drive_item_id_from_guid_rejects_bad_inputs() -> None:
    assert sharepoint_drive_item_id_from_guid(b"\x01\x02\x03", _GUID) is None
    assert sharepoint_drive_item_id_from_guid(b"\x01\x02\x03\x04", "not-a-guid") is None
