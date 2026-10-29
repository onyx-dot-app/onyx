from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import IO, Any
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.storage_file_document import (
    build_storage_file_document,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    Document,
    ImageSection,
    TabularSection,
    TextSection,
)
from onyx.file_processing.extract_file_text import ExtractionResult
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
        include_embedded_images=False,
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


def test_embedded_images_use_the_metadata_link() -> None:
    metadata_link = "https://example.com/source-page"

    def extract(
        file: IO[Any],  # noqa: ARG001
        file_name: str,  # noqa: ARG001
        image_callback: Callable[[bytes, str], None] | None,
    ) -> ExtractionResult:
        assert image_callback is not None
        image_callback(b"image", "figure.png")
        return ExtractionResult(
            text_content="body", embedded_images=[], metadata={"link": metadata_link}
        )

    def store(*_: Any, **__: Any) -> tuple[ImageSection, str]:
        return ImageSection(image_file_id="figure", link=LINK), "figure"

    with (
        patch(f"{MODULE}.extract_text_and_images", side_effect=extract),
        patch(
            "onyx.file_processing.image_utils.get_image_type_from_bytes",
            return_value="image/png",
        ),
        patch(
            "onyx.file_processing.image_utils.store_image_and_create_section",
            side_effect=store,
        ),
    ):
        document = build_storage_file_document(
            file_bytes=b"%PDF",
            file_name="report.pdf",
            document_id="s3:bucket:dir/report.pdf",
            source=DocumentSource.S3,
            link=LINK,
            last_modified=LAST_MODIFIED,
            image_file_id="s3_bucket_dir_report",
            raw_file_callback=None,
            include_embedded_images=True,
        )

    assert document is not None
    assert [section.link for section in document.sections] == [
        metadata_link,
        metadata_link,
    ]


def test_onyx_metadata_overrides_the_storage_fields() -> None:
    extraction = ExtractionResult(
        text_content="body",
        embedded_images=[],
        metadata={
            "link": "https://override.example.com/doc",
            "connector_type": "web",
            "file_display_name": "Override Name",
            "doc_updated_at": "2025-05-06T07:08:09Z",
            "primary_owners": ["alice@example.com"],
            "secondary_owners": ["bob@example.com"],
            "team": "search",
        },
    )
    with patch(f"{MODULE}.extract_text_and_images", return_value=extraction):
        document = _build("notes.txt", b"ignored")

    assert document is not None
    assert document.sections == [
        TextSection(link="https://override.example.com/doc", text="body")
    ]
    assert document.source == DocumentSource.WEB
    assert document.semantic_identifier == "Override Name"
    assert document.doc_updated_at == datetime(2025, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
    assert document.primary_owners == [
        BasicExpertInfo(display_name="alice@example.com")
    ]
    assert document.secondary_owners == [
        BasicExpertInfo(display_name="bob@example.com")
    ]
    assert document.metadata == {"team": "search"}
