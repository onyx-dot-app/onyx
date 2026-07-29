"""Extraction of user-posted attachments from Discord messages.

Discord users routinely paste a screenshot or drop a PDF into a channel with
little or no accompanying text. This module pulls those attachments off the
message and downloads them so they can be forwarded to Onyx as chat files, which
is what makes them visible to the agent (see `OnyxAPIClient.upload_chat_files`).

Only the formats Onyx accepts as chat files are downloaded — anything else would
be rejected server-side (or, worse, mis-classified), so it is reported as skipped
instead. Images become `ChatFileType.IMAGE` and are passed to the model as image
content; PDFs become `ChatFileType.DOC` and have their extracted text injected
into the prompt, so they work regardless of whether the model supports vision.
"""

import os

import discord
from pydantic import BaseModel

from onyx.file_processing.file_types import PDF_MIME_TYPE
from onyx.onyxbot.discord.constants import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_TOTAL_ATTACHMENT_BYTES,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

PDF_EXTENSION = ".pdf"

# The media type sent to Onyx for each extension we forward.
#
# Derived from the extension rather than trusted from Discord because the two
# signals have to agree server-side: the upload endpoint accepts or rejects by
# extension, while the resulting descriptor's `ChatFileType` comes from the
# content type. Discord's `content_type` is optional and occasionally generic, so
# taking it at face value would drop legitimately-named files or classify them as
# the wrong `ChatFileType`. `test_attachments.py` pins the keys to the extensions
# Onyx accepts and the values to media types it recognises.
_EXTENSION_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    PDF_EXTENSION: PDF_MIME_TYPE,
}


class MessageAttachment(BaseModel):
    """A downloaded Discord attachment, ready to upload to Onyx."""

    filename: str
    content_type: str
    data: bytes


class CollectedAttachments(BaseModel):
    """Attachments pulled off a Discord message, plus what had to be left out.

    `skipped_filenames` covers attachments Onyx could have used but that could
    not be included (unsupported format, too large, or a failed download).
    Callers surface these to the agent so it doesn't answer as if it had seen
    everything the user posted.
    """

    files: list[MessageAttachment] = []
    skipped_filenames: list[str] = []


def _normalized_content_type(attachment: discord.Attachment) -> str:
    """Lowercased media type with any parameters (e.g. `; charset=`) stripped."""
    if not attachment.content_type:
        return ""
    return attachment.content_type.split(";")[0].strip().lower()


def _file_extension(filename: str) -> str:
    """Lowercased extension, matching the server's `get_file_ext`.

    Must stay equivalent to it: an attachment we call supported here is one the
    upload endpoint has to classify the same way. `splitext` (rather than
    splitting on the last dot) is what makes an extensionless name like "pdf"
    yield "" on both sides.
    """
    return os.path.splitext(filename)[1].lower()


def is_forwardable_attachment(attachment: discord.Attachment) -> bool:
    """Whether this is the kind of attachment the bot tries to forward at all.

    Deliberately broader than `is_supported_attachment` — by either signal — so
    that a pasted GIF, or a PDF whose name lost its extension, is reported as
    skipped rather than silently ignored. Attachment kinds outside this set
    (spreadsheets, archives, source files) are left alone.
    """
    content_type = _normalized_content_type(attachment)
    return (
        is_supported_attachment(attachment)
        or content_type.startswith("image/")
        or content_type == PDF_MIME_TYPE
    )


def is_supported_attachment(attachment: discord.Attachment) -> bool:
    """Whether Onyx will accept this attachment as a chat file.

    Keyed on the extension because that is what the upload endpoint accepts or
    rejects on; `upload_content_type` then supplies a matching media type.
    """
    return _file_extension(attachment.filename) in _EXTENSION_CONTENT_TYPES


def upload_content_type(attachment: discord.Attachment) -> str:
    """The media type to send to Onyx for a supported attachment."""
    return _EXTENSION_CONTENT_TYPES[_file_extension(attachment.filename)]


async def collect_attachments(message: discord.Message) -> CollectedAttachments:
    """Download the supported attachments on a Discord message.

    Never raises: a message whose attachments can't be fetched still gets
    answered on its text alone.
    """
    candidates = [
        attachment
        for attachment in message.attachments
        if is_forwardable_attachment(attachment)
    ]
    if not candidates:
        return CollectedAttachments()

    collected = CollectedAttachments()
    total_bytes = 0

    for attachment in candidates:
        if len(collected.files) >= MAX_ATTACHMENTS_PER_MESSAGE:
            logger.warning(
                "Skipping attachment '%s': more than %s attachments on one message",
                attachment.filename,
                MAX_ATTACHMENTS_PER_MESSAGE,
            )
            collected.skipped_filenames.append(attachment.filename)
            continue

        if not is_supported_attachment(attachment):
            logger.info(
                "Skipping attachment '%s' (%s): unsupported format",
                attachment.filename,
                _normalized_content_type(attachment) or "unknown type",
            )
            collected.skipped_filenames.append(attachment.filename)
            continue

        if attachment.size > MAX_ATTACHMENT_BYTES:
            logger.warning(
                "Skipping attachment '%s': %s bytes exceeds the %s byte limit",
                attachment.filename,
                attachment.size,
                MAX_ATTACHMENT_BYTES,
            )
            collected.skipped_filenames.append(attachment.filename)
            continue

        if total_bytes + attachment.size > MAX_TOTAL_ATTACHMENT_BYTES:
            logger.warning(
                "Skipping attachment '%s': would exceed the %s byte per-message limit",
                attachment.filename,
                MAX_TOTAL_ATTACHMENT_BYTES,
            )
            collected.skipped_filenames.append(attachment.filename)
            continue

        try:
            data = await attachment.read()
        except Exception as e:
            # Broad on purpose: a CDN hiccup surfaces as a DiscordException, a
            # raw aiohttp error, or a timeout depending on where it fails, and
            # none of them should stop the bot from answering the message text.
            logger.warning(
                "Failed to download attachment '%s': %s", attachment.filename, e
            )
            collected.skipped_filenames.append(attachment.filename)
            continue

        total_bytes += len(data)
        collected.files.append(
            MessageAttachment(
                filename=attachment.filename,
                content_type=upload_content_type(attachment),
                data=data,
            )
        )

    logger.debug(
        "Collected %s attachment(s) (%s skipped) from message %s",
        len(collected.files),
        len(collected.skipped_filenames),
        message.id,
    )
    return collected
