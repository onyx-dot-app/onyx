"""Prepare Onyx message content, attachments, reminders, and token estimates."""

import json
from collections.abc import Callable, Sequence

from pydantic import BaseModel

from onyx.configs.app_configs import ENABLE_AZURE_IMAGE_CAP, PROMPT_CACHE_CHAT_HISTORY
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    SystemMessage,
    TextContentPart,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.utils import model_supports_image_input
from onyx.prompts.chat_prompts import IMAGE_DROP_REMINDER, NON_VISION_IMAGE_MARKER
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE, SYSTEM_REMINDER_TAG_OPEN
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Azure OpenAI documents a 50-image limit per request; other Azure-hosted
# models don't publish one. When ENABLE_AZURE_IMAGE_CAP=true is set, we cap
# all Azure providers at 50 to avoid raw 400s from the gateway. Off by
# default — no cap is applied to any provider.
_AZURE_DEFAULT_IMAGE_CAP = 50


class PromptMetadata(BaseModel):
    token_count: int | None = None
    image_files: list[ChatLoadedFile] | None = None
    image_token_count: int = 0
    should_cache: bool = False
    file_id: str | None = None
    is_reminder: bool = False
    omit_tool_result_content: bool = False


def prompt_metadata(message: Message) -> PromptMetadata:
    """Return request metadata without changing the message content."""
    return (
        message.metadata
        if isinstance(message.metadata, PromptMetadata)
        else PromptMetadata()
    )


def count_message_tokens(message: Message, token_counter: Callable[[str], int]) -> int:
    metadata = prompt_metadata(message)
    if metadata.token_count is not None:
        return metadata.token_count
    count = token_counter(message.text)
    if isinstance(message, AssistantMessage):
        count += sum(
            token_counter(json.dumps(call.arguments)) for call in message.tool_calls
        )
        if message.thinking_blocks:
            count += token_counter(
                json.dumps([block.model_dump() for block in message.thinking_blocks])
            )
    return count


def resolve_image_cap(model_provider: str) -> int | None:
    """Return the configured Azure image limit, or None for uncapped requests."""
    if ENABLE_AZURE_IMAGE_CAP and model_provider.startswith("azure"):
        return _AZURE_DEFAULT_IMAGE_CAP
    return None


def _user_content_parts(
    message: UserMessage,
) -> list[TextContentPart | ImageContentPart | ChatLoadedFile]:
    # Keep native content order; file bytes stay lazy until image selection finishes.
    parts: list[TextContentPart | ImageContentPart | ChatLoadedFile] = (
        [TextContentPart(text=message.content)]
        if isinstance(message.content, str)
        else list(message.content)
    )
    parts.extend(
        image
        for image in prompt_metadata(message).image_files or []
        if image.file_type == ChatFileType.IMAGE
    )
    return parts


def _select_recent_image_indices(
    history: Sequence[Message], cap: int
) -> tuple[set[tuple[int, int]], int]:
    """Pick which (msg_idx, part_idx) positions to keep when the request has
    more images than the cap. Walks messages newest-to-oldest (recency wins
    across turns) but walks images within each message in attachment order
    (earlier positions preferred). This matters in mixed messages where
    user-attached images appear first in image_files and project-context
    images are appended at the end — when the cap bites, we prefer to keep
    what the user explicitly attached over project-context fill.

    Returns the keep-set and the count of images that would be dropped. Only
    image parts on non-reminder user messages count, so cap slots aren't
    wasted on images that would never reach the LLM.
    """
    keep: set[tuple[int, int]] = set()
    total = 0
    for msg_idx in range(len(history) - 1, -1, -1):
        msg = history[msg_idx]
        if not isinstance(msg, UserMessage) or prompt_metadata(msg).is_reminder:
            continue
        for part_idx, part in enumerate(_user_content_parts(msg)):
            if isinstance(part, TextContentPart):
                continue
            total += 1
            if len(keep) < cap:
                keep.add((msg_idx, part_idx))
    return keep, max(0, total - cap)


def _format_user_message(
    message: UserMessage,
    message_index: int,
    supports_images: bool,
    keep_images: set[tuple[int, int]] | None,
) -> UserMessage:
    if isinstance(message.content, str) and not prompt_metadata(message).image_files:
        return UserMessage(content=message.content)
    content: list[TextContentPart | ImageContentPart] = []
    for part_index, part in enumerate(_user_content_parts(message)):
        if isinstance(part, TextContentPart):
            content.append(part)
            continue
        if keep_images is not None and (message_index, part_index) not in keep_images:
            continue
        # History can contain images even when the current model cannot accept
        # them (e.g. the user switched models mid-session). Sending them yields a
        # provider 400, so replay a text marker instead.
        if not supports_images:
            marker = (
                NON_VISION_IMAGE_MARKER.format(file_id=part.file_id)
                if isinstance(part, ChatLoadedFile)
                else "[Image omitted: the selected model does not support image input.]"
            )
            content.append(TextContentPart(text=marker))
        elif isinstance(part, ImageContentPart):
            content.append(part)
        else:
            try:
                image_type = get_image_type_from_bytes(part.content)
                image_url = f"data:{image_type};base64,{part.to_base64()}"
                content.extend(
                    [
                        TextContentPart(
                            text=f"[attached image — file_id: {part.file_id}]"
                        ),
                        ImageContentPart(
                            image_url=ImageUrlDetail(url=image_url, detail=None)
                        ),
                    ]
                )
            except Exception as error:
                logger.warning(
                    "Failed to load image %s: %s. Skipping image.",
                    part.file_id,
                    error,
                    exc_info=True,
                )
    return UserMessage(content=content)


def prepare_model_messages(  # noqa: C901
    history: Sequence[Message],
    llm_config: LLMConfig,
) -> list[Message]:
    """Resolve application attachments and reminders into shared model messages."""
    messages: list[Message] = []
    # Replay images as text markers when the selected model does not accept images.
    supports_image_input = True
    if any(
        isinstance(msg, UserMessage)
        and not prompt_metadata(msg).is_reminder
        and any(
            not isinstance(part, TextContentPart) for part in _user_content_parts(msg)
        )
        for msg in history
    ):
        supports_image_input = (
            llm_config.supports_images
            if llm_config.supports_images is not None
            else model_supports_image_input(
                llm_config.model_name,
                llm_config.model_provider,
                llm_config.deployment_name,
            )
        )

    # Native images and file attachments share one request limit. Text markers use no slots.
    image_cap = (
        resolve_image_cap(llm_config.model_provider) if supports_image_input else None
    )
    keep_image_indices: set[tuple[int, int]] | None = None
    image_drop_notice: str | None = None
    if image_cap is not None:
        keep_image_indices, dropped_image_count = _select_recent_image_indices(
            history, image_cap
        )
        if dropped_image_count > 0:
            logger.warning(
                "Image cap enforced: provider=%s model=%s cap=%d dropped=%d",
                llm_config.model_provider,
                llm_config.model_name,
                image_cap,
                dropped_image_count,
            )
            image_drop_notice = IMAGE_DROP_REMINDER.format(
                dropped_count=dropped_image_count
            )

    for idx, msg in enumerate(history):
        if isinstance(msg, SystemMessage):
            messages.append(msg.model_copy(deep=True))

        elif isinstance(msg, UserMessage) and not prompt_metadata(msg).is_reminder:
            messages.append(
                _format_user_message(msg, idx, supports_image_input, keep_image_indices)
            )

        elif isinstance(msg, UserMessage) and prompt_metadata(msg).is_reminder:
            # Mark application reminders within ordinary user content.
            wrapped_content = (
                f"{SYSTEM_REMINDER_TAG_OPEN}\n{msg.text}\n{SYSTEM_REMINDER_TAG_CLOSE}"
            )
            reminder_msg = UserMessage(
                content=wrapped_content,
            )
            messages.append(reminder_msg)

        elif isinstance(msg, (AssistantMessage, ToolResultMessage)):
            messages.append(msg.model_copy(deep=True))

        else:
            raise TypeError(f"Unsupported message type: {type(msg).__name__}")

        messages[-1].cacheable = (
            msg.cacheable
            or PROMPT_CACHE_CHAT_HISTORY
            and prompt_metadata(msg).should_cache
        )

    # Tell the model when image limits removed content from the request.
    if image_drop_notice is not None:
        wrapped = (
            f"{SYSTEM_REMINDER_TAG_OPEN}\n"
            f"{image_drop_notice}\n"
            f"{SYSTEM_REMINDER_TAG_CLOSE}"
        )
        messages.append(UserMessage(content=wrapped))

    return messages
