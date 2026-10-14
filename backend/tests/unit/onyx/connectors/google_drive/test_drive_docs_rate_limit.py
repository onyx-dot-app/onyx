"""A Docs-API rate limit is retried; one that outlasts the retries fails the
document instead of indexing its basic text, so the next run fetches it again.
Other Docs-API errors still fall back to the basic text."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.doc_conversion import (
    FileExtractionResult,
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import ConnectorFailure, Document, TextSection

_GATEWAY_MODULE = "onyx.connectors.google_drive.source_operations"
_USER = "user@example.com"
_DOC = {"tabs": []}


def _http_error(status: int, reason: str | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    body: dict[str, Any] = {"error": {"errors": [{"reason": reason}] if reason else []}}
    response._content = json.dumps(body).encode()
    return requests.HTTPError(f"{status} error", response=response)


def _broken_stream(**_kwargs: Any) -> Iterator[bytes]:
    yield b'{"tabs"'
    raise requests.exceptions.ChunkedEncodingError("connection broken")


def _response(error: Exception | None) -> MagicMock:
    response = MagicMock()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    if isinstance(error, requests.exceptions.ChunkedEncodingError):
        response.iter_content = MagicMock(side_effect=_broken_stream)
    else:
        response.raise_for_status = MagicMock(side_effect=error)
        response.iter_content = MagicMock(
            return_value=iter([json.dumps(_DOC).encode()])
        )
    return response


def _fetch(errors: list[Exception | None]) -> tuple[Any, MagicMock]:
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.get = MagicMock(side_effect=[_response(error) for error in errors])
    ops = GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(None, "google_drive", {})
    )
    with (
        patch.object(GoogleDriveSourceOperations, "_creds", return_value=MagicMock()),
        patch(f"{_GATEWAY_MODULE}.get_google_authorized_session", return_value=session),
        patch("time.sleep"),
    ):
        try:
            return (
                ops.fetch_google_doc(
                    user_email=_USER, doc_id="doc", max_response_bytes=10_000
                ),
                session,
            )
        except GoogleDriveHttpError as error:
            return error, session


@pytest.mark.parametrize(
    "error",
    [
        _http_error(429),
        _http_error(403, "userRateLimitExceeded"),
        requests.exceptions.ChunkedEncodingError("connection broken"),
    ],
)
def test_a_transient_error_is_retried(error: Exception) -> None:
    result, session = _fetch([error, None])

    assert result == _DOC
    assert session.get.call_count == 2


def test_a_rate_limit_that_outlasts_the_retries_raises() -> None:
    result, session = _fetch([_http_error(429)] * 5)

    assert isinstance(result, GoogleDriveHttpError)
    assert result.rate_limited
    assert session.get.call_count == 5


def test_an_access_error_is_not_retried() -> None:
    result, session = _fetch([_http_error(403, "accessNotConfigured")])

    assert isinstance(result, GoogleDriveHttpError)
    assert not result.transient
    assert session.get.call_count == 1


def _convert(fetch_error: Exception) -> Document | ConnectorFailure | None:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_doc.side_effect = fetch_error
    basic = FileExtractionResult(
        sections=[TextSection(text="basic text", link="https://docs/doc")]
    )
    with patch.object(
        doc_conversion, "_download_and_extract_sections_basic", return_value=basic
    ):
        return convert_drive_item_to_document(
            ops,
            allow_images=False,
            size_threshold=10_000,
            permission_sync_context=None,
            retriever_emails=[_USER, "admin@example.com"],
            file={
                "id": "doc",
                "name": "A doc",
                "mimeType": GDriveMimeType.DOC.value,
                "webViewLink": "https://docs.google.com/document/d/doc/edit",
                "modifiedTime": "2026-10-01T00:00:00+00:00",
            },
        )


@pytest.mark.parametrize(
    "error",
    [
        GoogleDriveHttpError(
            status_code=429, reasons=(), access_denied=False, message="429"
        ),
        GoogleDriveHttpError(
            status_code=403,
            reasons=("userRateLimitExceeded",),
            access_denied=False,
            message="403 rate limit",
        ),
    ],
)
def test_a_lasting_rate_limit_fails_the_document(error: GoogleDriveHttpError) -> None:
    result = _convert(error)

    assert isinstance(result, ConnectorFailure)
    assert result.failed_document is not None


def test_another_docs_error_keeps_the_basic_text() -> None:
    result = _convert(
        GoogleDriveHttpError(
            status_code=403,
            reasons=("accessNotConfigured",),
            access_denied=True,
            message="Docs API disabled",
        )
    )

    assert isinstance(result, Document)
    assert [section.text for section in result.sections] == ["basic text"]
