"""Build native agent history from persisted chat records."""

from pydantic_ai import messages as pm

from onyx.chat.models import ChatMessageSimple
from onyx.configs.app_configs import ENABLE_AZURE_IMAGE_CAP, PROMPT_CACHE_CHAT_HISTORY
from onyx.configs.constants import MessageType
from onyx.configs.model_configs import ENABLE_PROMPT_CACHING
from onyx.file_store.models import ChatFileType
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import (
    model_needs_formatting_reenabled,
    model_supports_image_input,
    supports_explicit_cache,
)
from onyx.prompts.chat_prompts import (
    CODE_BLOCK_MARKDOWN,
    IMAGE_DROP_REMINDER,
    NON_VISION_IMAGE_MARKER,
)
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE, SYSTEM_REMINDER_TAG_OPEN
from onyx.tools.tool_name import sanitize_tool_name
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Azure OpenAI documents a 50-image limit per request; other Azure-hosted
# models don't publish one. When ENABLE_AZURE_IMAGE_CAP=true is set, we cap
# all Azure providers at 50 to avoid raw 400s from the gateway. Off by
# default — no cap is applied to any provider.
_AZURE_DEFAULT_IMAGE_CAP = 50


def _is_azure_provider(model_provider: str) -> bool:
    """True for any provider whose name starts with 'azure'."""
    return model_provider.startswith("azure")


def resolve_image_cap(model_provider: str) -> int | None:
    """Return the per-request image-count cap, or None if no cap should be
    enforced. Only Azure providers are capped, and only when
    ENABLE_AZURE_IMAGE_CAP=true is set."""
    if ENABLE_AZURE_IMAGE_CAP and _is_azure_provider(model_provider):
        return _AZURE_DEFAULT_IMAGE_CAP
    return None


def _select_recent_image_indices(
    history: list[ChatMessageSimple], cap: int
) -> tuple[set[tuple[int, int]], int]:
    """Pick which (msg_idx, img_idx) positions to keep when the request has
    more images than the cap. Walks messages newest-to-oldest (recency wins
    across turns) but walks images within each message in attachment order
    (earlier positions preferred). This matters in mixed messages where
    user-attached images appear first in image_files and project-context
    images are appended at the end — when the cap bites, we prefer to keep
    what the user explicitly attached over project-context fill.

    Returns the keep-set and the count of images that would be dropped. Only
    ChatFileType.IMAGE entries on USER messages count — that matches what
    translate_history_to_native_messages actually emits, so cap slots aren't
    wasted on images that would never reach the LLM."""
    keep: set[tuple[int, int]] = set()
    total = 0
    kept = 0
    for msg_idx in range(len(history) - 1, -1, -1):
        msg = history[msg_idx]
        if msg.message_type != MessageType.USER or not msg.image_files:
            continue
        for img_idx, img in enumerate(msg.image_files):
            if img.file_type != ChatFileType.IMAGE:
                continue
            total += 1
            if kept < cap:
                keep.add((msg_idx, img_idx))
                kept += 1
    return keep, max(0, total - cap)


def translate_history_to_native_messages(
    history: list[ChatMessageSimple], llm_config: LLMConfig
) -> list[pm.ModelMessage]:
    """Keep provider-neutral messages native from the persistence boundary onward."""
    supports_images = not any(
        msg.image_files for msg in history
    ) or model_supports_image_input(
        llm_config.model_name, llm_config.model_provider, llm_config.deployment_name
    )
    cap = resolve_image_cap(llm_config.model_provider) if supports_images else None
    keep_images, dropped = (
        _select_recent_image_indices(history, cap) if cap is not None else (None, 0)
    )
    messages: list[pm.ModelMessage] = []
    tool_names: dict[str, str] = {}
    cache_prefix = ENABLE_PROMPT_CACHING and PROMPT_CACHE_CHAT_HISTORY
    cache_index: int | None = None
    formatting_added = False
    for index, record in enumerate(history):
        message: pm.ModelMessage
        if record.message_type == MessageType.SYSTEM:
            text = record.message
            if not formatting_added and model_needs_formatting_reenabled(
                llm_config.model_name, llm_config.deployment_name
            ):
                text = CODE_BLOCK_MARKDOWN + text
                formatting_added = True
            message = pm.ModelRequest(parts=[pm.SystemPromptPart(text)])
        elif record.message_type in {MessageType.USER, MessageType.USER_REMINDER}:
            text = record.message
            if record.message_type == MessageType.USER_REMINDER:
                text = (
                    f"{SYSTEM_REMINDER_TAG_OPEN}\n{text}\n{SYSTEM_REMINDER_TAG_CLOSE}"
                )
            content: list[pm.UserContent] = [text]
            for image_index, image in enumerate(record.image_files or []):
                if (
                    record.message_type != MessageType.USER
                    or image.file_type != ChatFileType.IMAGE
                ):
                    continue
                if keep_images is not None and (index, image_index) not in keep_images:
                    continue
                if not supports_images:
                    content.append(
                        NON_VISION_IMAGE_MARKER.format(file_id=image.file_id)
                    )
                    continue
                try:
                    media_type = get_image_type_from_bytes(image.content)
                    content.extend(
                        [
                            f"[attached image — file_id: {image.file_id}]",
                            pm.BinaryContent(data=image.content, media_type=media_type),
                        ]
                    )
                except Exception as error:
                    logger.warning(
                        "Failed to process image file %s: %s. Skipping image.",
                        image.file_id,
                        error,
                    )
            message = pm.ModelRequest(
                parts=[pm.UserPromptPart(content if len(content) > 1 else text)]
            )
        elif record.message_type == MessageType.ASSISTANT:
            parts: list[pm.ModelResponsePart] = (
                [pm.TextPart(record.message)] if record.message else []
            )
            for call in record.tool_calls or []:
                name = sanitize_tool_name(call.tool_name)
                tool_names[call.tool_call_id] = name
                parts.append(
                    pm.ToolCallPart(name, call.tool_arguments, call.tool_call_id)
                )
            if not parts:
                continue
            message = pm.ModelResponse(
                parts=parts, provider_name=llm_config.model_provider
            )
        elif record.message_type == MessageType.TOOL_CALL_RESPONSE:
            if not record.tool_call_id:
                raise ValueError(
                    "Tool call response message encountered but tool_call_id is not available."
                )
            message = pm.ModelRequest(
                parts=[
                    pm.ToolReturnPart(
                        tool_names.get(record.tool_call_id, "tool"),
                        record.message,
                        record.tool_call_id,
                    )
                ]
            )
        else:
            logger.warning(
                "Unknown message type %s in history. Skipping message.",
                record.message_type,
            )
            continue
        if record.file_id:
            message.metadata = {"onyx_file_id": record.file_id}
        messages.append(message)
        cache_prefix = cache_prefix and record.should_cache
        if cache_prefix:
            cache_index = len(messages) - 1

    # Explicit history cache points apply to Anthropic user content. Other
    # providers retain their native instruction or implicit caching settings.
    if supports_explicit_cache(llm_config) and cache_index is not None:
        cached = messages[cache_index]
        if isinstance(cached, pm.ModelRequest) and isinstance(
            cached.parts[-1], pm.UserPromptPart
        ):
            part = cached.parts[-1]
            part.content = (
                [part.content, pm.CachePoint()]
                if isinstance(part.content, str)
                else [*part.content, pm.CachePoint()]
            )
    if dropped:
        logger.warning(
            "Image cap enforced: provider=%s model=%s cap=%d dropped=%d",
            llm_config.model_provider,
            llm_config.model_name,
            cap,
            dropped,
        )
        notice = IMAGE_DROP_REMINDER.format(dropped_count=dropped)
        messages.append(
            pm.ModelRequest(
                parts=[
                    pm.UserPromptPart(
                        f"{SYSTEM_REMINDER_TAG_OPEN}\n{notice}\n{SYSTEM_REMINDER_TAG_CLOSE}"
                    )
                ]
            )
        )
    return messages
