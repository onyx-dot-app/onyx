"""Tests for GoogleDriveConnector.normalize_url hostname validation and normalization.

The original implementation used ``netloc.startswith(("docs.google.com", "drive.google.com"))``
which accepted spoofed hostnames such as ``docs.google.com.evil.com`` and normalized them as
real Drive document IDs. This test suite validates the fix (exact hostname matching via
``parsed.hostname``) and covers the standard URL normalization behavior end-to-end.
"""

from onyx.connectors.google_drive.connector import GoogleDriveConnector

_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz12345"


def _normalize(url: str) -> str | None:
    return GoogleDriveConnector.normalize_url(url).normalized_url


# ── Canonical form stripping ──────────────────────────────────────────────────


def test_native_doc_strips_edit_suffix() -> None:
    assert _normalize(
        f"https://docs.google.com/document/d/{_ID}/edit"
    ) == f"https://docs.google.com/document/d/{_ID}"


def test_native_doc_strips_query_and_fragment() -> None:
    assert _normalize(
        f"https://docs.google.com/document/d/{_ID}/edit?usp=sharing#top"
    ) == f"https://docs.google.com/document/d/{_ID}"


def test_drive_file_d_view_form() -> None:
    assert _normalize(
        f"https://drive.google.com/file/d/{_ID}/view"
    ) == f"https://drive.google.com/file/d/{_ID}"


def test_drive_file_d_no_view_suffix() -> None:
    assert _normalize(
        f"https://drive.google.com/file/d/{_ID}"
    ) == f"https://drive.google.com/file/d/{_ID}"


def test_multi_account_u_form() -> None:
    assert _normalize(
        f"https://docs.google.com/document/u/0/d/{_ID}/edit"
    ) == f"https://docs.google.com/document/d/{_ID}"


def test_id_query_param_uses_binary_canonical_form() -> None:
    """``?id={id}`` is type-ambiguous, so the binary-file canonical form is used."""
    assert _normalize(
        f"https://drive.google.com/open?id={_ID}"
    ) == f"https://drive.google.com/file/d/{_ID}"


def test_spreadsheet_canonical_form() -> None:
    assert _normalize(
        f"https://docs.google.com/spreadsheets/d/{_ID}/edit#gid=0"
    ) == f"https://docs.google.com/spreadsheets/d/{_ID}"


def test_presentation_canonical_form() -> None:
    assert _normalize(
        f"https://docs.google.com/presentation/d/{_ID}/edit"
    ) == f"https://docs.google.com/presentation/d/{_ID}"


# ── Candidate document IDs ───────────────────────────────────────────────────


def test_candidates_include_all_native_types_for_file_d() -> None:
    """A type-ambiguous ``/file/d/`` URL lists doc, sheet, slide, and file forms."""
    result = GoogleDriveConnector.normalize_url(
        f"https://drive.google.com/file/d/{_ID}"
    )
    assert result.normalized_url == f"https://drive.google.com/file/d/{_ID}"
    assert set(result.candidate_document_ids) == {
        f"https://docs.google.com/document/d/{_ID}",
        f"https://docs.google.com/spreadsheets/d/{_ID}",
        f"https://docs.google.com/presentation/d/{_ID}",
        f"https://drive.google.com/file/d/{_ID}",
    }


# ── Hostname spoofing / domain validation ────────────────────────────────────


def test_rejects_spoofed_docs_google_com_evil() -> None:
    """Pre-prefix-spoofing bug: ``docs.google.com.evil.com`` was accepted."""
    result = GoogleDriveConnector.normalize_url(
        f"https://docs.google.com.evil.com/document/d/{_ID}"
    )
    assert result.normalized_url is None
    assert result.use_default is False


def test_rejects_spoofed_drive_google_com_evil() -> None:
    result = GoogleDriveConnector.normalize_url(
        f"https://drive.google.com.evil.com/file/d/{_ID}"
    )
    assert result.normalized_url is None
    assert result.use_default is False


def test_rejects_subdomain_docs_google_com() -> None:
    result = GoogleDriveConnector.normalize_url(
        f"https://foo.docs.google.com/document/d/{_ID}/edit"
    )
    assert result.normalized_url is None
    assert result.use_default is False


def test_rejects_non_google_host() -> None:
    result = GoogleDriveConnector.normalize_url(
        f"https://example.com/something/d/{_ID}"
    )
    assert result.normalized_url is None
    assert result.use_default is False


def test_rejects_empty_netloc() -> None:
    result = GoogleDriveConnector.normalize_url(f"/document/d/{_ID}")
    assert result.normalized_url is None


def test_rejects_malformed_hostname() -> None:
    result = GoogleDriveConnector.normalize_url(
        f"https://[docs.google.com/document/d/{_ID}"
    )
    assert result.normalized_url is None
    assert result.use_default is False


def test_rejects_url_without_file_id() -> None:
    result = GoogleDriveConnector.normalize_url("https://docs.google.com/document/")
    assert result.normalized_url is None
