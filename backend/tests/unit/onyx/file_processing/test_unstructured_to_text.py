import json
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from onyx.file_processing.unstructured import unstructured_to_text

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _mock_client(
    elements: list[dict[str, Any]] | None, status_code: int = 200
) -> mock.MagicMock:
    """Build a stand-in UnstructuredClient whose partition call returns `elements`."""
    response = mock.MagicMock()
    response.status_code = status_code
    response.elements = elements

    client = mock.MagicMock()
    client.general.partition.return_value = response
    return client


def _run(elements: list[dict[str, Any]] | None, status_code: int = 200) -> str:
    client_cls = mock.MagicMock(return_value=_mock_client(elements, status_code))
    with (
        mock.patch("unstructured_client.UnstructuredClient", client_cls),
        mock.patch(
            "onyx.file_processing.unstructured.get_unstructured_api_key",
            return_value="fake-key",
        ),
    ):
        return unstructured_to_text(BytesIO(b"file contents"), "test.pdf")


def test_elements_are_joined_with_blank_lines() -> None:
    """Element text is concatenated in order, separated by a blank line."""
    elements = [
        {"type": "Title", "element_id": "a", "text": "The Title"},
        {"type": "NarrativeText", "element_id": "b", "text": "First paragraph."},
        {"type": "NarrativeText", "element_id": "c", "text": "Second paragraph."},
    ]
    assert _run(elements) == "The Title\n\nFirst paragraph.\n\nSecond paragraph."


def test_element_metadata_is_ignored() -> None:
    """Only the text of each element reaches the output, never its metadata."""
    elements = [
        {
            "type": "NarrativeText",
            "element_id": "a",
            "text": "Body text.",
            "metadata": {"filename": "test.pdf", "page_number": 1},
        }
    ]
    assert _run(elements) == "Body text."


def test_textless_elements_become_empty_strings() -> None:
    """Elements that carry no text still occupy their position in the output."""
    elements = [
        {"type": "Title", "element_id": "a", "text": "Heading"},
        {"type": "Image", "element_id": "b", "text": ""},
        {"type": "NarrativeText", "element_id": "c", "text": "Body."},
    ]
    assert _run(elements) == "Heading\n\n\n\nBody."


def test_no_elements_returns_empty_string() -> None:
    """An empty element list and a null element list both yield no text."""
    assert _run([]) == ""
    assert _run(None) == ""


def test_non_200_status_raises() -> None:
    """A failed partition call raises instead of returning partial text."""
    with pytest.raises(ValueError, match="unexpected status code 500"):
        _run([{"type": "Title", "element_id": "a", "text": "x"}], status_code=500)


def test_file_is_read_from_the_start() -> None:
    """An already-consumed file is rewound so its full contents are uploaded."""
    file = BytesIO(b"file contents")
    file.read()

    client = _mock_client([{"type": "Title", "element_id": "a", "text": "x"}])
    with (
        mock.patch("unstructured_client.UnstructuredClient", return_value=client),
        mock.patch(
            "onyx.file_processing.unstructured.get_unstructured_api_key",
            return_value="fake-key",
        ),
    ):
        unstructured_to_text(file, "test.pdf")

    request = client.general.partition.call_args.kwargs["request"]
    assert request.partition_parameters.files.content == b"file contents"


def test_real_partition_payload() -> None:
    """A recorded Unstructured payload produces the same text the old path did.

    The fixture is the API's own serialization of a partitioned HTML document,
    so it carries the real element shape: mixed types, nested metadata, a table
    with `text_as_html`, and an image whose text is its alt attribute. The
    expected string was captured from the previous `dict_to_elements`
    implementation before it was removed.
    """
    elements = json.loads(
        (FIXTURES_DIR / "unstructured_partition_elements.json").read_text()
    )
    assert _run(elements) == (
        "Quarterly Report\n\n"
        "Revenue grew 12% this quarter.\n\n"
        "North America: up 8%\n\n"
        "EMEA: up 19%\n\n"
        "Region Total NA 4.2M\n\n"
        "chart"
    )
