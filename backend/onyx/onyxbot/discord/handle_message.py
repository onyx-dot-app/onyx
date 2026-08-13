"""Discord bot message handling and response logic."""

import asyncio
from collections import Counter

import discord
from pydantic import BaseModel

from onyx.chat.models import ChatFullResponse
from onyx.db.discord_bot import (
    get_channel_config_by_discord_ids,
    get_guild_config_by_discord_id,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import DiscordChannelConfig, DiscordGuildConfig
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.onyxbot.discord.api_client import OnyxAPIClient
from onyx.onyxbot.discord.attachments import collect_attachments
from onyx.onyxbot.discord.constants import (
    MAX_CONTEXT_MESSAGES,
    MAX_MESSAGE_LENGTH,
    THINKING_EMOJI,
)
from onyx.onyxbot.discord.exceptions import APIError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Message types with actual content (excludes system notifications like "user joined")
CONTENT_MESSAGE_TYPES = (
    discord.MessageType.default,
    discord.MessageType.reply,
    discord.MessageType.thread_starter_message,
)


class ShouldRespondContext(BaseModel):
    """Context for whether the bot should respond to a message."""

    should_respond: bool
    persona_id: int | None
    thread_only_mode: bool


# -------------------------------------------------------------------------
# Response Logic
# -------------------------------------------------------------------------


async def should_respond(
    message: discord.Message,
    tenant_id: str,
    bot_user: discord.ClientUser,
) -> ShouldRespondContext:
    """Determine if bot should respond and which persona to use."""
    if not message.guild:
        logger.warning("Received a message that isn't in a server.")
        return ShouldRespondContext(
            should_respond=False, persona_id=None, thread_only_mode=False
        )

    guild_id = message.guild.id
    channel_id = message.channel.id
    bot_mentioned = bot_user in message.mentions

    def _get_configs() -> tuple[DiscordGuildConfig | None, DiscordChannelConfig | None]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            guild_config = get_guild_config_by_discord_id(db, guild_id)
            if not guild_config or not guild_config.enabled:
                return None, None

            # For threads, use parent channel ID
            actual_channel_id = channel_id
            if isinstance(message.channel, discord.Thread) and message.channel.parent:
                actual_channel_id = message.channel.parent.id

            channel_config = get_channel_config_by_discord_ids(
                db, guild_id, actual_channel_id
            )
            return guild_config, channel_config

    guild_config, channel_config = await asyncio.to_thread(_get_configs)

    if not guild_config or not channel_config or not channel_config.enabled:
        return ShouldRespondContext(
            should_respond=False, persona_id=None, thread_only_mode=False
        )

    # Determine persona (channel override or guild default)
    persona_id = channel_config.persona_override_id or guild_config.default_persona_id

    # Check mention requirement (with exceptions for implicit invocation)
    if channel_config.require_bot_invocation and not bot_mentioned:
        if not await check_implicit_invocation(message, bot_user):
            return ShouldRespondContext(
                should_respond=False, persona_id=None, thread_only_mode=False
            )

    return ShouldRespondContext(
        should_respond=True,
        persona_id=persona_id,
        thread_only_mode=channel_config.thread_only_mode,
    )


async def check_implicit_invocation(
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> bool:
    """Check if the bot should respond without explicit mention.

    Returns True if:
    1. User is replying to a bot message
    2. User is in a thread owned by the bot
    3. User is in a thread created from a bot message
    """
    # Check if replying to a bot message
    if message.reference and message.reference.message_id:
        try:
            referenced_msg = await message.channel.fetch_message(
                message.reference.message_id
            )
            if referenced_msg.author.id == bot_user.id:
                logger.debug(
                    "Implicit invocation via reply: '%s...'", message.content[:50]
                )
                return True
        except (discord.NotFound, discord.HTTPException):
            pass

    # Check thread-related conditions
    if isinstance(message.channel, discord.Thread):
        thread = message.channel

        # Bot owns the thread
        if thread.owner_id == bot_user.id:
            logger.debug(
                "Implicit invocation via bot-owned thread: '%s...' in #%s",
                message.content[:50],
                thread.name,
            )
            return True

        # Thread was created from a bot message
        if thread.parent and not isinstance(thread.parent, discord.ForumChannel):
            try:
                starter = await thread.parent.fetch_message(thread.id)
                if starter.author.id == bot_user.id:
                    logger.debug(
                        "Implicit invocation via bot-started thread: '%s...' in #%s",
                        message.content[:50],
                        thread.name,
                    )
                    return True
            except (discord.NotFound, discord.HTTPException):
                pass

    return False


# -------------------------------------------------------------------------
# Message Processing
# -------------------------------------------------------------------------


async def process_chat_message(
    message: discord.Message,
    api_key: str,
    persona_id: int | None,
    thread_only_mode: bool,
    api_client: OnyxAPIClient,
    bot_user: discord.ClientUser,
) -> None:
    """Process a message and send response."""
    try:
        await message.add_reaction(THINKING_EMOJI)
    except discord.DiscordException:
        logger.warning(
            "Failed to add thinking reaction to message: '%s...'", message.content[:50]
        )

    try:
        # Build conversation context
        context = await _build_conversation_context(message, bot_user)

        # Forward any pasted images / PDFs so the agent gets them with the text
        file_descriptors, unavailable_files = await _prepare_attachments(
            message=message,
            api_key=api_key,
            api_client=api_client,
        )

        # Prepare full message content
        parts = []
        if context:
            parts.append(context)
        if isinstance(message.channel, discord.Thread):
            if isinstance(message.channel.parent, discord.ForumChannel):
                parts.append(f"Forum post title: {message.channel.name}")
        parts.append(
            f"Current message from @{message.author.display_name}: {format_message_content(message)}"
        )

        response = await _request_answer(
            api_client=api_client,
            api_key=api_key,
            persona_id=persona_id,
            parts=parts,
            file_descriptors=file_descriptors,
            unavailable_files=unavailable_files,
        )

        # Format response with citations
        answer = response.answer or "I couldn't generate a response."
        answer = _append_citations(answer, response)

        await send_response(message, answer, thread_only_mode)

        try:
            await message.remove_reaction(THINKING_EMOJI, bot_user)
        except discord.DiscordException:
            pass

    except APIError as e:
        logger.error("API error processing message: %s", e)
        await send_error_response(message, bot_user)
    except Exception as e:
        logger.exception("Error processing chat message: %s", e)
        await send_error_response(message, bot_user)


def _build_message_text(parts: list[str], unavailable_files: list[str]) -> str:
    """Join the message parts, naming any attachments the agent won't see."""
    if not unavailable_files:
        return "\n\n".join(parts)

    return "\n\n".join(
        parts
        + [
            "Note: these attachments could not be read and are not "
            f"available to you: {', '.join(unavailable_files)}"
        ]
    )


def _is_image(descriptor: FileDescriptor) -> bool:
    return descriptor.get("type") == ChatFileType.IMAGE


async def _request_answer(
    api_client: OnyxAPIClient,
    api_key: str,
    persona_id: int | None,
    parts: list[str],
    file_descriptors: list[FileDescriptor],
    unavailable_files: list[str],
) -> ChatFullResponse:
    """Ask Onyx for an answer, retrying without the images if they can't be used.

    Not every model accepts image input, and a provider-side rejection would
    otherwise turn an answerable question into an error reply. Retrying without
    them degrades to the behaviour from before images were forwarded at all, and
    tells the agent what it is missing. Documents are kept on the retry — their
    text is injected into the prompt, so no model can refuse them. Only retried
    when the first attempt produced no answer at all, so a partial answer with a
    warning is never thrown away.
    """
    images = [descriptor for descriptor in file_descriptors if _is_image(descriptor)]

    if not images:
        # Nothing the model can refuse outright, so there is no lighter request
        # to fall back to.
        return await api_client.send_chat_message(
            message=_build_message_text(parts, unavailable_files),
            api_key=api_key,
            persona_id=persona_id,
            file_descriptors=file_descriptors,
        )

    failure: str | None
    try:
        response = await api_client.send_chat_message(
            message=_build_message_text(parts, unavailable_files),
            api_key=api_key,
            persona_id=persona_id,
            file_descriptors=file_descriptors,
        )
        if response.answer.strip() or not response.error_msg:
            return response
        failure = response.error_msg
    except APIError as e:
        failure = str(e)

    logger.warning(
        "Chat request with %s image(s) failed (%s); retrying without them",
        len(images),
        failure,
    )

    return await api_client.send_chat_message(
        message=_build_message_text(
            parts,
            unavailable_files
            + [descriptor.get("name") or "image" for descriptor in images],
        ),
        api_key=api_key,
        persona_id=persona_id,
        file_descriptors=[
            descriptor for descriptor in file_descriptors if not _is_image(descriptor)
        ],
    )


async def _prepare_attachments(
    message: discord.Message,
    api_key: str,
    api_client: OnyxAPIClient,
) -> tuple[list[FileDescriptor], list[str]]:
    """Download attachments posted with the message and upload them to Onyx.

    Returns the descriptors to attach to the chat request plus the filenames of
    attachments that couldn't be included. Failing to forward them never fails
    the message: the agent answers on the text and is told what it is missing.
    """
    collected = await collect_attachments(message)
    if not collected.files:
        return [], collected.skipped_filenames

    try:
        file_descriptors = await api_client.upload_chat_files(
            files=collected.files,
            api_key=api_key,
        )
    except APIError as e:
        logger.error("Failed to upload %s attachment(s): %s", len(collected.files), e)
        return [], collected.skipped_filenames + [
            file.filename for file in collected.files
        ]

    # The server can reject individual files (e.g. an unreadable or
    # password-protected PDF, or one over its token limit); those are absent from
    # the descriptors it returns. Counted rather than set-matched because pasted
    # screenshots routinely share the name "image.png".
    uploaded_counts = Counter(descriptor.get("name") for descriptor in file_descriptors)
    rejected_names: list[str] = []
    for file in collected.files:
        if uploaded_counts[file.filename] > 0:
            uploaded_counts[file.filename] -= 1
        else:
            rejected_names.append(file.filename)

    logger.info(
        "Attached %s file(s) to Discord message %s (%s unavailable)",
        len(file_descriptors),
        message.id,
        len(collected.skipped_filenames) + len(rejected_names),
    )

    return file_descriptors, collected.skipped_filenames + rejected_names


async def _build_conversation_context(
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> str | None:
    """Build conversation context from thread history or reply chain."""
    if isinstance(message.channel, discord.Thread):
        return await _build_thread_context(message, bot_user)
    elif message.reference:
        return await _build_reply_chain_context(message, bot_user)
    return None


def _append_citations(answer: str, response: ChatFullResponse) -> str:
    """Append citation sources to the answer if present."""
    if not response.citation_info or not response.top_documents:
        return answer

    cited_docs: list[tuple[int, str, str | None]] = []
    for citation in response.citation_info:
        doc = next(
            (
                d
                for d in response.top_documents
                if d.document_id == citation.document_id
            ),
            None,
        )
        if doc:
            cited_docs.append(
                (
                    citation.citation_number,
                    doc.semantic_identifier or "Source",
                    doc.link,
                )
            )

    if not cited_docs:
        return answer

    cited_docs.sort(key=lambda x: x[0])
    citations = "\n\n**Sources:**\n"
    for num, name, link in cited_docs[:5]:
        if link:
            citations += f"{num}. [{name}](<{link}>)\n"
        else:
            citations += f"{num}. {name}\n"

    return answer + citations


# -------------------------------------------------------------------------
# Context Building
# -------------------------------------------------------------------------


async def _build_reply_chain_context(
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> str | None:
    """Build context by following the reply chain backwards."""
    if not message.reference or not message.reference.message_id:
        return None

    try:
        messages: list[discord.Message] = []
        current = message

        # Follow reply chain backwards up to MAX_CONTEXT_MESSAGES
        while (
            current.reference
            and current.reference.message_id
            and len(messages) < MAX_CONTEXT_MESSAGES
        ):
            try:
                parent = await message.channel.fetch_message(
                    current.reference.message_id
                )
                messages.append(parent)
                current = parent
            except (discord.NotFound, discord.HTTPException):
                break

        if not messages:
            return None

        messages.reverse()  # Chronological order

        logger.debug(
            "Built reply chain context: %s messages in #%s",
            len(messages),
            getattr(message.channel, "name", "unknown"),
        )

        return _format_messages_as_context(messages, bot_user)

    except Exception as e:
        logger.warning("Failed to build reply chain context: %s", e)
        return None


async def _build_thread_context(
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> str | None:
    """Build context from thread message history."""
    if not isinstance(message.channel, discord.Thread):
        return None

    try:
        thread = message.channel
        messages: list[discord.Message] = []

        # Fetch recent messages (excluding current)
        async for msg in thread.history(limit=MAX_CONTEXT_MESSAGES, oldest_first=False):
            if msg.id != message.id:
                messages.append(msg)

        # Include thread starter message and its reply chain if not already present
        if thread.parent and not isinstance(thread.parent, discord.ForumChannel):
            try:
                starter = await thread.parent.fetch_message(thread.id)
                if starter.id != message.id and not any(
                    m.id == starter.id for m in messages
                ):
                    messages.append(starter)

                # Trace back through the starter's reply chain for more context
                current = starter
                while (
                    current.reference
                    and current.reference.message_id
                    and len(messages) < MAX_CONTEXT_MESSAGES
                ):
                    try:
                        parent = await thread.parent.fetch_message(
                            current.reference.message_id
                        )
                        if not any(m.id == parent.id for m in messages):
                            messages.append(parent)
                        current = parent
                    except (discord.NotFound, discord.HTTPException):
                        break
            except (discord.NotFound, discord.HTTPException):
                pass

        if not messages:
            return None

        messages.sort(key=lambda m: m.id)  # Chronological order
        logger.debug(
            "Built thread context: %s messages in #%s", len(messages), thread.name
        )

        return _format_messages_as_context(messages, bot_user)

    except Exception as e:
        logger.warning("Failed to build thread context: %s", e)
        return None


def _format_messages_as_context(
    messages: list[discord.Message],
    bot_user: discord.ClientUser,
) -> str | None:
    """Format a list of messages into a conversation context string."""
    formatted = []
    for msg in messages:
        if msg.type not in CONTENT_MESSAGE_TYPES:
            continue

        sender = (
            "OnyxBot" if msg.author.id == bot_user.id else f"@{msg.author.display_name}"
        )
        formatted.append(f"{sender}: {format_message_content(msg)}")

    if not formatted:
        return None

    return (
        "You are a Discord bot named OnyxBot.\n"
        'Always assume that [user] is the same as the "Current message" author.\n'
        "Attachments named in the conversation history are not available to you; "
        "only attachments on the current message are.\n"
        "Conversation history:\n"
        "---\n" + "\n".join(formatted) + "\n---"
    )


# -------------------------------------------------------------------------
# Message Formatting
# -------------------------------------------------------------------------


def format_message_content(message: discord.Message) -> str:
    """Format message content with readable mentions and attachment markers.

    Attachments are named inline because a Discord message can consist of
    nothing but a pasted screenshot — without a marker such a message would read
    as empty text to the agent.
    """
    content = message.content

    for user in message.mentions:
        content = content.replace(f"<@{user.id}>", f"@{user.display_name}")
        content = content.replace(f"<@!{user.id}>", f"@{user.display_name}")

    for role in message.role_mentions:
        content = content.replace(f"<@&{role.id}>", f"@{role.name}")

    for channel in message.channel_mentions:
        content = content.replace(f"<#{channel.id}>", f"#{channel.name}")

    markers = [
        f"[attachment: {attachment.filename}]" for attachment in message.attachments
    ]
    if markers:
        content = " ".join([content.strip(), *markers]).strip()

    return content


# -------------------------------------------------------------------------
# Response Sending
# -------------------------------------------------------------------------


async def send_response(
    message: discord.Message,
    content: str,
    thread_only_mode: bool,
) -> None:
    """Send response based on thread_only_mode setting."""
    chunks = _split_message(content)

    if isinstance(message.channel, discord.Thread):
        for chunk in chunks:
            await message.channel.send(chunk)
    elif thread_only_mode:
        thread_name = f"OnyxBot <> {message.author.display_name}"[:100]
        thread = await message.create_thread(name=thread_name)
        for chunk in chunks:
            await thread.send(chunk)
    else:
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)


def _split_message(content: str) -> list[str]:
    """Split content into chunks that fit Discord's message limit."""
    chunks = []
    while content:
        if len(content) <= MAX_MESSAGE_LENGTH:
            chunks.append(content)
            break

        # Find a good split point
        split_at = MAX_MESSAGE_LENGTH
        for sep in ["\n\n", "\n", ". ", " "]:
            idx = content.rfind(sep, 0, MAX_MESSAGE_LENGTH)
            if idx > MAX_MESSAGE_LENGTH // 2:
                split_at = idx + len(sep)
                break

        chunks.append(content[:split_at])
        content = content[split_at:]

    return chunks


async def send_error_response(
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> None:
    """Send error response and clean up reaction."""
    try:
        await message.remove_reaction(THINKING_EMOJI, bot_user)
    except discord.DiscordException:
        pass

    error_msg = "Sorry, I encountered an error processing your message. You may want to contact Onyx for support :sweat_smile:"

    try:
        if isinstance(message.channel, discord.Thread):
            await message.channel.send(error_msg)
        else:
            thread = await message.create_thread(
                name=f"Response to {message.author.display_name}"[:100]
            )
            await thread.send(error_msg)
    except discord.DiscordException:
        pass
