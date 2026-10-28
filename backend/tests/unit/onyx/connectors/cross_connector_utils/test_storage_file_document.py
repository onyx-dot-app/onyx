from collections.abc import Generator
from datetime import datetime, timezone
from typing import IO
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.storage_file_document import (
    build_storage_file_document,
)
from onyx.connectors.models import Document, ImageSection, TabularSection, TextSection
from onyx.file_store.staging import RawFileCallback

MODULE = "onyx.connectors.cross_connector_utils.storage_file_document"
LINK = "https://storage.example.com/bucket/dir/file"
LAST_MODIFIED = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_unstructured_key() -> Generator[None, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


def _build(
    file_name: str,
    file_bytes: bytes,
    raw_file_callback: RawFileCallback | None = None,
) -> Document | None:
    return build_storage_file_document(
        file_bytes=file_bytes,
        file_name=file_name,
        document_id=f"s3:bucket:dir/{file_name}",
        source=DocumentSource.S3,
        link=LINK,
        last_modified=LAST_MODIFIED,
        image_file_id="s3_bucket_dir_image",
        raw_file_callback=raw_file_callback,
    )


def _stage(content: IO[bytes], content_type: str) -> str:
    return f"staged:{content_type}:{len(content.read())}"


def test_text_file_becomes_one_text_section() -> None:
    document = _build("notes.txt", b"  hello storage  ")

    assert document is not None
    assert document.id == "s3:bucket:dir/notes.txt"
    assert document.source == DocumentSource.S3
    assert document.semantic_identifier == "notes.txt"
    assert document.doc_updated_at == LAST_MODIFIED
    assert document.sections == [TextSection(link=LINK, text="hello storage")]


def test_empty_text_file_keeps_an_empty_section() -> None:
    document = _build("empty.txt", b"   ")

    assert document is not None
    assert document.sections == [TextSection(link=LINK, text="")]


def test_image_file_is_stored_as_an_image_section() -> None:
    image_section = ImageSection(image_file_id="s3_bucket_dir_image", link=LINK)
    with patch(
        f"{MODULE}.store_image_and_create_section",
        return_value=(image_section, None),
    ) as store:
        document = _build("square.png", b"png-bytes")

    assert store.call_args.kwargs["file_id"] == "s3_bucket_dir_image"
    assert store.call_args.kwargs["display_name"] == "square.png"
    assert document is not None
    assert document.sections == [image_section]
    assert document.metadata == {}


def test_tabular_file_is_staged() -> None:
    document = _build("table.csv", b"name,value\nalpha,1\n", raw_file_callback=_stage)

    assert document is not None
    assert document.file_id == "staged:text/csv:19"
    assert len(document.sections) == 1
    assert isinstance(document.sections[0], TabularSection)


def test_tabular_file_without_callback_is_skipped() -> None:
    assert _build("table.csv", b"name,value\nalpha,1\n") is None
