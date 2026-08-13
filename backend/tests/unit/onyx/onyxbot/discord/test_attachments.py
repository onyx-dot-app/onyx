"""Unit tests for Discord attachment collection.

Covers which attachments get forwarded to Onyx as chat files (images and PDFs)
and which are reported as skipped so the agent can be told what it is missing.
"""

from unittest.mock import MagicMock

import discord
import pytest

from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import (
    PDF_MIME_TYPE,
    OnyxFileExtensions,
    OnyxMimeTypes,
)
from onyx.onyxbot.discord import attachments
from onyx.onyxbot.discord.attachments import (
    collect_attachments,
    is_forwardable_attachment,
    is_supported_attachment,
    upload_content_type,
)
from onyx.onyxbot.discord.constants import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
)
from tests.unit.onyx.onyxbot.discord.conftest import mock_attachment, mock_message


class TestSupportedExtensionMap:
    """The extension→media-type map must stay aligned with what Onyx accepts."""

    def test_covers_every_image_extension_onyx_accepts(self) -> None:
        """If Onyx adds an image format, this map has to learn about it."""
        assert set(attachments._EXTENSION_CONTENT_TYPES) == (
            OnyxFileExtensions.IMAGE_EXTENSIONS | {attachments.PDF_EXTENSION}
        )

    def test_every_media_type_is_one_onyx_recognises(self) -> None:
        """A media type Onyx doesn't know maps to the wrong ChatFileType."""
        recognised = OnyxMimeTypes.IMAGE_MIME_TYPES | {PDF_MIME_TYPE}
        assert set(attachments._EXTENSION_CONTENT_TYPES.values()) <= recognised


class TestAttachmentClassification:
    """Tests for is_forwardable_attachment / is_supported_attachment."""

    def test_png_is_supported(self) -> None:
        attachment = mock_attachment(filename="shot.png", content_type="image/png")
        assert is_forwardable_attachment(attachment)
        assert is_supported_attachment(attachment)

    def test_pdf_is_supported(self) -> None:
        attachment = mock_attachment(
            filename="report.pdf", content_type="application/pdf"
        )
        assert is_forwardable_attachment(attachment)
        assert is_supported_attachment(attachment)

    def test_uppercase_extension_is_supported(self) -> None:
        attachment = mock_attachment(filename="REPORT.PDF", content_type=None)
        assert is_supported_attachment(attachment)

    def test_gif_is_forwardable_but_not_supported(self) -> None:
        attachment = mock_attachment(filename="clip.gif", content_type="image/gif")
        assert is_forwardable_attachment(attachment)
        assert not is_supported_attachment(attachment)

    def test_missing_content_type_still_works_from_the_extension(self) -> None:
        """Discord's content_type is optional; the extension is authoritative."""
        for filename in ("shot.png", "report.pdf"):
            attachment = mock_attachment(filename=filename, content_type=None)
            assert is_forwardable_attachment(attachment), filename
            assert is_supported_attachment(attachment), filename

    def test_generic_content_type_still_works_from_the_extension(self) -> None:
        attachment = mock_attachment(
            filename="report.pdf", content_type="application/octet-stream"
        )
        assert is_supported_attachment(attachment)

    def test_content_type_parameters_are_ignored(self) -> None:
        """Discord occasionally appends parameters to the media type."""
        attachment = mock_attachment(
            filename="clip.gif", content_type="Image/GIF; charset=utf-8"
        )
        assert is_forwardable_attachment(attachment)
        assert not is_supported_attachment(attachment)

    @pytest.mark.parametrize(
        "filename",
        ["shot.png", "report.pdf", "pdf", "png", "noext", ".pdf", "a.b.PDF"],
    )
    def test_extension_matches_the_server(self, filename: str) -> None:
        """Client and server must classify extensions identically.

        A mismatch means uploading a file the server then rejects — e.g. an
        attachment literally named "pdf", which has no extension by `splitext`.
        """
        assert attachments._file_extension(filename) == get_file_ext(filename)

    def test_extensionless_name_is_reported_not_forwarded(self) -> None:
        """The server keys on extension, so "pdf" is unusable — but say so."""
        attachment = mock_attachment(filename="pdf", content_type="application/pdf")
        assert is_forwardable_attachment(attachment)
        assert not is_supported_attachment(attachment)

    def test_other_document_types_are_left_alone(self) -> None:
        """Only images and PDFs are in scope; a .docx is not forwarded."""
        attachment = mock_attachment(
            filename="notes.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        )
        assert not is_forwardable_attachment(attachment)


class TestUploadContentType:
    """Tests for the media type sent to Onyx."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("shot.png", "image/png"),
            ("shot.JPG", "image/jpeg"),
            ("shot.jpeg", "image/jpeg"),
            ("shot.webp", "image/webp"),
            ("report.pdf", "application/pdf"),
        ],
    )
    def test_media_type_comes_from_the_extension(
        self, filename: str, expected: str
    ) -> None:
        attachment = mock_attachment(filename=filename, content_type=None)
        assert upload_content_type(attachment) == expected

    def test_discord_content_type_is_not_trusted(self) -> None:
        """A generic type from Discord would classify the file wrongly."""
        attachment = mock_attachment(
            filename="report.pdf", content_type="application/octet-stream"
        )
        assert upload_content_type(attachment) == "application/pdf"


class TestCollectAttachments:
    """Tests for collect_attachments."""

    @pytest.mark.asyncio
    async def test_no_attachments(self) -> None:
        collected = await collect_attachments(mock_message())
        assert collected.files == []
        assert collected.skipped_filenames == []

    @pytest.mark.asyncio
    async def test_supported_image_is_downloaded(self) -> None:
        message = mock_message(
            content="what's wrong here?",
            attachments=[mock_attachment(filename="bug.png", data=b"png-bytes")],
        )

        collected = await collect_attachments(message)

        assert len(collected.files) == 1
        file = collected.files[0]
        assert file.filename == "bug.png"
        assert file.content_type == "image/png"
        assert file.data == b"png-bytes"
        assert collected.skipped_filenames == []

    @pytest.mark.asyncio
    async def test_pdf_is_downloaded(self) -> None:
        message = mock_message(
            content="summarise this",
            attachments=[
                mock_attachment(
                    filename="report.pdf",
                    content_type="application/pdf",
                    data=b"%PDF-1.7 bytes",
                )
            ],
        )

        collected = await collect_attachments(message)

        assert len(collected.files) == 1
        file = collected.files[0]
        assert file.filename == "report.pdf"
        assert file.content_type == "application/pdf"
        assert file.data == b"%PDF-1.7 bytes"
        assert collected.skipped_filenames == []

    @pytest.mark.asyncio
    async def test_mixed_image_and_pdf_preserve_order(self) -> None:
        message = mock_message(
            attachments=[
                mock_attachment(filename="one.png", data=b"one"),
                mock_attachment(
                    filename="two.pdf", content_type="application/pdf", data=b"two"
                ),
                mock_attachment(filename="three.jpg", content_type="image/jpeg"),
            ]
        )

        collected = await collect_attachments(message)

        assert [file.filename for file in collected.files] == [
            "one.png",
            "two.pdf",
            "three.jpg",
        ]

    @pytest.mark.asyncio
    async def test_out_of_scope_attachments_are_ignored(self) -> None:
        """Spreadsheets and the like are neither forwarded nor reported."""
        message = mock_message(
            attachments=[mock_attachment(filename="data.csv", content_type="text/csv")]
        )

        collected = await collect_attachments(message)

        assert collected.files == []
        assert collected.skipped_filenames == []

    @pytest.mark.asyncio
    async def test_unsupported_image_format_is_skipped(self) -> None:
        message = mock_message(
            attachments=[mock_attachment(filename="clip.gif", content_type="image/gif")]
        )

        collected = await collect_attachments(message)

        assert collected.files == []
        assert collected.skipped_filenames == ["clip.gif"]

    @pytest.mark.asyncio
    async def test_oversized_file_is_skipped_without_downloading(self) -> None:
        attachment = mock_attachment(
            filename="huge.pdf",
            content_type="application/pdf",
            size=MAX_ATTACHMENT_BYTES + 1,
        )
        message = mock_message(attachments=[attachment])

        collected = await collect_attachments(message)

        assert collected.files == []
        assert collected.skipped_filenames == ["huge.pdf"]
        attachment.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_message_byte_budget_is_enforced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once the per-message budget is spent, later attachments are skipped."""
        monkeypatch.setattr(attachments, "MAX_TOTAL_ATTACHMENT_BYTES", 10)
        message = mock_message(
            attachments=[
                mock_attachment(filename="first.png", size=8, data=b"12345678"),
                mock_attachment(filename="second.png", size=8, data=b"12345678"),
            ]
        )

        collected = await collect_attachments(message)

        assert [file.filename for file in collected.files] == ["first.png"]
        assert collected.skipped_filenames == ["second.png"]

    @pytest.mark.asyncio
    async def test_per_message_count_limit_is_enforced(self) -> None:
        over_limit = MAX_ATTACHMENTS_PER_MESSAGE + 2
        message = mock_message(
            attachments=[
                mock_attachment(filename=f"shot{index}.png")
                for index in range(over_limit)
            ]
        )

        collected = await collect_attachments(message)

        assert len(collected.files) == MAX_ATTACHMENTS_PER_MESSAGE
        assert len(collected.skipped_filenames) == 2

    @pytest.mark.asyncio
    async def test_failed_download_is_skipped(self) -> None:
        message = mock_message(
            attachments=[
                mock_attachment(
                    filename="gone.png",
                    read_error=discord.NotFound(MagicMock(), "gone"),
                ),
                mock_attachment(filename="fine.png"),
            ]
        )

        collected = await collect_attachments(message)

        assert [file.filename for file in collected.files] == ["fine.png"]
        assert collected.skipped_filenames == ["gone.png"]

    @pytest.mark.asyncio
    async def test_non_discord_download_error_is_skipped(self) -> None:
        """A CDN failure can surface as a raw transport error, not a DiscordException."""
        message = mock_message(
            attachments=[
                mock_attachment(
                    filename="slow.pdf",
                    content_type="application/pdf",
                    read_error=TimeoutError("timeout"),
                ),
                mock_attachment(filename="fine.png"),
            ]
        )

        collected = await collect_attachments(message)

        assert [file.filename for file in collected.files] == ["fine.png"]
        assert collected.skipped_filenames == ["slow.pdf"]
