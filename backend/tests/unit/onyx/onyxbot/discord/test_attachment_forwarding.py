"""Unit tests for forwarding Discord attachments to the Onyx chat API.

Covers `_prepare_attachments` (upload + bookkeeping of what didn't make it), the
fallback that drops images when a model can't use them, and the attachment
markers `format_message_content` adds so an attachment-only message doesn't read
as empty text.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.onyxbot.discord.exceptions import APIResponseError
from onyx.onyxbot.discord.handle_message import (
    _prepare_attachments,
    _request_answer,
    format_message_content,
)
from tests.unit.onyx.onyxbot.discord.conftest import mock_attachment, mock_message


def _descriptor(
    name: str, file_type: ChatFileType = ChatFileType.IMAGE
) -> FileDescriptor:
    return FileDescriptor(
        id=f"file-store-id-{name}",
        type=file_type,
        name=name,
        user_file_id=f"user-file-id-{name}",
    )


def _doc_descriptor(name: str) -> FileDescriptor:
    return _descriptor(name, file_type=ChatFileType.DOC)


def _api_client(
    descriptors: list[FileDescriptor] | None = None,
    error: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    client.upload_chat_files = AsyncMock(
        side_effect=error, return_value=descriptors or []
    )
    return client


def _chat_response(answer: str = "hello", error_msg: str | None = None) -> MagicMock:
    response = MagicMock()
    response.answer = answer
    response.error_msg = error_msg
    return response


def _sending_client(*responses: Any) -> MagicMock:
    """Client whose send_chat_message yields `responses` in order.

    Values that are exceptions are raised instead of returned.
    """
    client = MagicMock()
    client.send_chat_message = AsyncMock(side_effect=list(responses))
    return client


class TestPrepareAttachments:
    """Tests for _prepare_attachments."""

    @pytest.mark.asyncio
    async def test_no_attachments_skips_upload(self) -> None:
        api_client = _api_client()

        descriptors, unavailable = await _prepare_attachments(
            message=mock_message(),
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == []
        assert unavailable == []
        api_client.upload_chat_files.assert_not_called()

    @pytest.mark.asyncio
    async def test_images_are_uploaded_and_returned(self) -> None:
        api_client = _api_client([_descriptor("bug.png")])
        message = mock_message(
            content="see attached", attachments=[mock_attachment(filename="bug.png")]
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == [_descriptor("bug.png")]
        assert unavailable == []
        upload_kwargs = api_client.upload_chat_files.call_args.kwargs
        assert upload_kwargs["api_key"] == "key"
        assert [file.filename for file in upload_kwargs["files"]] == ["bug.png"]

    @pytest.mark.asyncio
    async def test_pdfs_are_uploaded_and_returned(self) -> None:
        api_client = _api_client([_doc_descriptor("report.pdf")])
        message = mock_message(
            content="summarise this",
            attachments=[
                mock_attachment(filename="report.pdf", content_type="application/pdf")
            ],
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == [_doc_descriptor("report.pdf")]
        assert unavailable == []
        upload_kwargs = api_client.upload_chat_files.call_args.kwargs
        assert [file.filename for file in upload_kwargs["files"]] == ["report.pdf"]
        assert [file.content_type for file in upload_kwargs["files"]] == [
            "application/pdf"
        ]

    @pytest.mark.asyncio
    async def test_upload_failure_degrades_to_text_only(self) -> None:
        """An upload error must not fail the message — only lose the files."""
        api_client = _api_client(error=APIResponseError("boom", status_code=500))
        message = mock_message(
            attachments=[
                mock_attachment(filename="bug.png"),
                mock_attachment(filename="report.pdf", content_type="application/pdf"),
            ]
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == []
        assert unavailable == ["bug.png", "report.pdf"]

    @pytest.mark.asyncio
    async def test_server_rejected_file_is_reported_unavailable(self) -> None:
        """The server omits rejected files from its response.

        A password-protected or unreadable PDF is the common case.
        """
        api_client = _api_client([_doc_descriptor("good.pdf")])
        message = mock_message(
            attachments=[
                mock_attachment(filename="good.pdf", content_type="application/pdf"),
                mock_attachment(filename="locked.pdf", content_type="application/pdf"),
            ]
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == [_doc_descriptor("good.pdf")]
        assert unavailable == ["locked.pdf"]

    @pytest.mark.asyncio
    async def test_duplicate_filenames_are_counted_not_deduplicated(self) -> None:
        """Pasted screenshots routinely share the name "image.png"."""
        api_client = _api_client([_descriptor("image.png")])
        message = mock_message(
            attachments=[
                mock_attachment(filename="image.png"),
                mock_attachment(filename="image.png"),
            ]
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert len(descriptors) == 1
        assert unavailable == ["image.png"]

    @pytest.mark.asyncio
    async def test_locally_skipped_files_are_reported(self) -> None:
        """An unsupported format never reaches the server but is still reported."""
        api_client = _api_client([_descriptor("good.png")])
        message = mock_message(
            attachments=[
                mock_attachment(filename="good.png"),
                mock_attachment(filename="clip.gif", content_type="image/gif"),
            ]
        )

        descriptors, unavailable = await _prepare_attachments(
            message=message,
            api_key="key",
            api_client=api_client,
        )

        assert descriptors == [_descriptor("good.png")]
        assert unavailable == ["clip.gif"]
        assert [
            file.filename
            for file in api_client.upload_chat_files.call_args.kwargs["files"]
        ] == ["good.png"]


class TestRequestAnswer:
    """Tests for the image-dropping fallback in _request_answer."""

    _PARTS = ["Current message from @User: look at this [attachment: shot.png]"]

    @pytest.mark.asyncio
    async def test_files_are_sent_on_the_first_attempt(self) -> None:
        api_client = _sending_client(_chat_response())

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=7,
            parts=self._PARTS,
            file_descriptors=[_descriptor("shot.png")],
            unavailable_files=[],
        )

        assert response.answer == "hello"
        api_client.send_chat_message.assert_called_once()
        kwargs = api_client.send_chat_message.call_args.kwargs
        assert kwargs["file_descriptors"] == [_descriptor("shot.png")]
        assert kwargs["persona_id"] == 7
        assert "could not be read" not in kwargs["message"]

    @pytest.mark.asyncio
    async def test_no_attachments_sends_once(self) -> None:
        api_client = _sending_client(_chat_response())

        await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[],
            unavailable_files=[],
        )

        api_client.send_chat_message.assert_called_once()
        assert api_client.send_chat_message.call_args.kwargs["file_descriptors"] == []

    @pytest.mark.asyncio
    async def test_pdf_only_failure_is_not_retried(self) -> None:
        """Document text is injected as plain text, so no model can refuse it.

        There is no lighter request to fall back to, and retrying identically
        would just burn a second LLM call.
        """
        api_client = _sending_client(_chat_response(answer="", error_msg="boom"))

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[_doc_descriptor("report.pdf")],
            unavailable_files=[],
        )

        assert response.error_msg == "boom"
        api_client.send_chat_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_answerless_error_retries_without_images(self) -> None:
        """A model that can't accept images must not cost the user their answer."""
        api_client = _sending_client(
            _chat_response(answer="", error_msg="model does not support image input"),
            _chat_response(answer="answered from the text"),
        )

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[_descriptor("shot.png")],
            unavailable_files=[],
        )

        assert response.answer == "answered from the text"
        assert api_client.send_chat_message.call_count == 2
        retry_kwargs = api_client.send_chat_message.call_args.kwargs
        assert retry_kwargs["file_descriptors"] == []
        assert "shot.png" in retry_kwargs["message"]
        assert "could not be read" in retry_kwargs["message"]

    @pytest.mark.asyncio
    async def test_retry_keeps_documents_and_drops_only_images(self) -> None:
        """A PDF's text is still usable even when the images have to go."""
        api_client = _sending_client(
            _chat_response(answer="", error_msg="model does not support image input"),
            _chat_response(answer="answered from the pdf"),
        )

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[
                _descriptor("shot.png"),
                _doc_descriptor("report.pdf"),
            ],
            unavailable_files=[],
        )

        assert response.answer == "answered from the pdf"
        retry_kwargs = api_client.send_chat_message.call_args.kwargs
        assert retry_kwargs["file_descriptors"] == [_doc_descriptor("report.pdf")]
        assert "shot.png" in retry_kwargs["message"]
        assert (
            "report.pdf" not in retry_kwargs["message"].split("could not be read")[-1]
        )

    @pytest.mark.asyncio
    async def test_api_error_retries_without_images(self) -> None:
        api_client = _sending_client(
            APIResponseError("bad request", status_code=400),
            _chat_response(answer="answered from the text"),
        )

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[_descriptor("shot.png")],
            unavailable_files=[],
        )

        assert response.answer == "answered from the text"
        assert api_client.send_chat_message.call_count == 2

    @pytest.mark.asyncio
    async def test_partial_answer_with_warning_is_kept(self) -> None:
        """An answer plus a warning is a success — retrying would discard it."""
        api_client = _sending_client(
            _chat_response(answer="partial answer", error_msg="some warning")
        )

        response = await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[_descriptor("shot.png")],
            unavailable_files=[],
        )

        assert response.answer == "partial answer"
        api_client.send_chat_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_attempt_error_propagates(self) -> None:
        """The retry gets no special treatment — a real failure still surfaces."""
        api_client = _sending_client(
            APIResponseError("bad request", status_code=400),
            APIResponseError("still broken", status_code=500),
        )

        with pytest.raises(APIResponseError) as exc_info:
            await _request_answer(
                api_client=api_client,
                api_key="key",
                persona_id=None,
                parts=self._PARTS,
                file_descriptors=[_descriptor("shot.png")],
                unavailable_files=[],
            )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_unavailable_files_are_named_for_the_agent(self) -> None:
        api_client = _sending_client(_chat_response())

        await _request_answer(
            api_client=api_client,
            api_key="key",
            persona_id=None,
            parts=self._PARTS,
            file_descriptors=[],
            unavailable_files=["clip.gif", "locked.pdf"],
        )

        message = api_client.send_chat_message.call_args.kwargs["message"]
        assert "could not be read" in message
        assert "clip.gif" in message
        assert "locked.pdf" in message


class TestAttachmentMarkers:
    """Tests for the attachment markers format_message_content adds."""

    def test_image_only_message_is_not_empty(self) -> None:
        message = mock_message(
            content="", attachments=[mock_attachment(filename="shot.png")]
        )

        assert format_message_content(message) == "[attachment: shot.png]"

    def test_marker_is_appended_after_text(self) -> None:
        message = mock_message(
            content="what is this?", attachments=[mock_attachment(filename="shot.png")]
        )

        assert format_message_content(message) == "what is this? [attachment: shot.png]"

    def test_every_attachment_is_named(self) -> None:
        message = mock_message(
            content="",
            attachments=[
                mock_attachment(filename="one.png"),
                mock_attachment(filename="notes.pdf", content_type="application/pdf"),
            ],
        )

        assert (
            format_message_content(message)
            == "[attachment: one.png] [attachment: notes.pdf]"
        )

    def test_message_without_attachments_is_unchanged(self) -> None:
        message = mock_message(content="just text")

        assert format_message_content(message) == "just text"
