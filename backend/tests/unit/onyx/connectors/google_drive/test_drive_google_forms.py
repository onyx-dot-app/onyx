"""A Google Form indexes its questions through the Forms API. With the Forms
API off, the Form is skipped without trying other users."""

from typing import Any
from unittest.mock import MagicMock

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
