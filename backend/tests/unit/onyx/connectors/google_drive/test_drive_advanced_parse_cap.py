"""fetch_google_doc bounds the Docs-API fetch: it returns None once the
streamed response exceeds the byte cap, and returns the document under it.
get_document_sections parses the fetched document."""

import json
from unittest.mock import MagicMock, patch

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)

_GATEWAY_MODULE = "onyx.connectors.google_drive.source_operations"
_USER = "user@example.com"


def _as_ctx(obj: MagicMock) -> MagicMock:
    obj.__enter__ = MagicMock(return_value=obj)
    obj.__exit__ = MagicMock(return_value=False)
    return obj


def _mock_session(chunks: list[bytes]) -> MagicMock:
    response = _as_ctx(MagicMock())
    response.raise_for_status = MagicMock()
    response.iter_content = MagicMock(return_value=iter(chunks))
    session = _as_ctx(MagicMock())
    session.get = MagicMock(return_value=response)
    return session


def _fetch(chunks: list[bytes], max_response_bytes: int) -> dict[str, object] | None:
    ops = GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(None, "google_drive", {})
    )
    with (
        patch.object(GoogleDriveSourceOperations, "_creds", return_value=MagicMock()),
        patch(
            f"{_GATEWAY_MODULE}.get_google_authorized_session",
            return_value=_mock_session(chunks),
        ),
    ):
        return ops.fetch_google_doc(
            user_email=_USER, doc_id="doc", max_response_bytes=max_response_bytes
        )


def test_fetch_google_doc_returns_none_over_cap() -> None:
    assert _fetch([b"a" * 80, b"b" * 80], max_response_bytes=100) is None


def test_fetch_google_doc_returns_document_under_cap() -> None:
    doc = {"tabs": []}
    assert _fetch([json.dumps(doc).encode()], max_response_bytes=10_000) == doc


def test_get_document_sections_parses_fetched_document() -> None:
    doc = {
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0"},
                "documentTab": {
                    "body": {
                        "content": [
                            {
                                "paragraph": {
                                    "paragraphStyle": {
                                        "namedStyleType": "HEADING_1",
                                        "headingId": "h.1",
                                    },
                                    "elements": [{"textRun": {"content": "Intro\n"}}],
                                }
                            },
                            {
                                "paragraph": {
                                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                    "elements": [{"textRun": {"content": "Body\n"}}],
                                }
                            },
                        ]
                    }
                },
            }
        ]
    }
    sections = get_document_sections(doc, "doc")
    assert [(section.text, section.link) for section in sections] == [
        (
            "Intro\nBody",
            "https://docs.google.com/document/d/doc/edit?tab=t.0#heading=h.1",
        )
    ]
    assert get_document_sections({"tabs": []}, "doc") == []
