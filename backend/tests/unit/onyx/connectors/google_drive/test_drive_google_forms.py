"""A Google Form indexes its questions through the Forms API. A Form over the
size threshold, or any Form while the Forms API is off, is skipped without
trying other users."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive.doc_conversion import convert_drive_item_to_document
from onyx.connectors.google_drive.form_extraction import get_form_text
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import ConnectorFailure, Document

_LINK = "https://docs.google.com/forms/d/form/edit"
_FORM: dict[str, Any] = {
    "info": {"title": "Product feedback", "description": "Tell us what you think."},
    "items": [
        {
            "title": "How did you hear about us?",
            "questionItem": {
                "question": {
                    "choiceQuestion": {
                        "type": "RADIO",
                        "options": [{"value": "Search"}, {"isOther": True}],
                    }
                }
            },
        },
        {
            "title": "How likely are you to recommend us?",
            "questionItem": {
                "question": {
                    "scaleQuestion": {
                        "low": 1,
                        "high": 5,
                        "lowLabel": "Unlikely",
                        "highLabel": "Very likely",
                    }
                }
            },
        },
        {
            "title": "Rate each feature",
            "questionGroupItem": {
                "questions": [{"rowQuestion": {"title": "Search quality"}}],
                "grid": {"columns": {"type": "RADIO", "options": [{"value": "Good"}]}},
            },
        },
        {"title": "Thanks!", "textItem": {}},
    ],
}


def test_form_text_holds_the_questions_and_choices() -> None:
    assert get_form_text(_FORM) == "\n".join(
        [
            "Product feedback",
            "Tell us what you think.",
            "How did you hear about us?",
            "- Search",
            "How likely are you to recommend us?",
            "Unlikely",
            "Very likely",
            "Rate each feature",
            "Search quality",
            "- Good",
            "Thanks!",
        ]
    )


def _convert(ops: MagicMock) -> Document | ConnectorFailure | None:
    return convert_drive_item_to_document(
        ops,
        allow_images=False,
        size_threshold=10_000,
        permission_sync_context=None,
        retriever_emails=["user@example.com", "admin@example.com"],
        file={
            "id": "form",
            "name": "Product feedback",
            "mimeType": GDriveMimeType.FORM.value,
            "webViewLink": _LINK,
            "modifiedTime": "2026-10-01T00:00:00+00:00",
            "size": "1024",
        },
    )


def test_a_form_indexes_its_questions_without_a_download() -> None:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_form.return_value = _FORM

    result = _convert(ops)

    assert isinstance(result, Document)
    assert [(section.link, section.text) for section in result.sections] == [
        (_LINK, get_form_text(_FORM))
    ]
    ops.download_file.assert_not_called()
    ops.export_file.assert_not_called()


def test_a_form_is_skipped_when_the_forms_api_is_off() -> None:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_form.side_effect = GoogleDriveHttpError(
        status_code=403,
        reasons=("SERVICE_DISABLED",),
        access_denied=True,
        message="Forms API disabled",
    )

    assert _convert(ops) is None
    ops.fetch_google_form.assert_called_once()


def test_a_form_over_the_size_threshold_is_skipped() -> None:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_form.return_value = None

    assert _convert(ops) is None
    ops.fetch_google_form.assert_called_once()
    assert ops.fetch_google_form.call_args.kwargs["max_response_bytes"] == 10_000


def _session(chunks: list[bytes]) -> MagicMock:
    response = MagicMock()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    response.iter_content = MagicMock(return_value=iter(chunks))
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.get = MagicMock(return_value=response)
    return session


def _fetch_form(chunks: list[bytes], max_response_bytes: int) -> dict[str, Any] | None:
    ops = GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(None, "google_drive", {})
    )
    with (
        patch.object(GoogleDriveSourceOperations, "_creds", return_value=MagicMock()),
        patch.object(
            GoogleDriveSourceOperations,
            "_docs_session",
            return_value=_session(chunks),
        ),
    ):
        return ops.fetch_google_form(
            user_email="user@example.com",
            form_id="form",
            max_response_bytes=max_response_bytes,
        )


def test_fetch_google_form_stops_reading_over_the_cap() -> None:
    assert _fetch_form([b"a" * 80, b"b" * 80], max_response_bytes=100) is None
    assert _fetch_form([json.dumps(_FORM).encode()], max_response_bytes=10_000) == _FORM
