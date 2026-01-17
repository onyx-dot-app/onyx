"""Discord bot message handling and response logic."""

import asyncio

import discord
from pydantic import BaseModel

from onyx.db.discord_bot import get_channel_config_by_discord_ids
from onyx.db.discord_bot import get_guild_config_by_discord_id
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import DiscordChannelConfig
from onyx.db.models import DiscordGuildConfig
from onyx.onyxbot.discord.api_client import OnyxAPIClient
from onyx.onyxbot.discord.constants import MAX_MESSAGE_LENGTH
from onyx.onyxbot.discord.constants import THINKING_EMOJI
from onyx.onyxbot.discord.exceptions import APIError
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
    bot_user: discord.User,
) -> ShouldRespondContext:
    """Determine if bot should respond and which persona to use.

    Returns: ShouldRespondContext with should_respond, persona_id, thread_only_mode
    """
    guild_id = message.guild.id
    channel_id = message.channel.id
    bot_mentioned = bot_user in message.mentions

    # Get guild and channel configs from database
    def _get_configs() -> tuple[DiscordGuildConfig | None, DiscordChannelConfig | None]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            guild_config = get_guild_config_by_discord_id(db, guild_id)
            if not guild_config or not guild_config.enabled:
                return None, None

            # For threads, use parent channel ID
            actual_channel_id = channel_id
            if isinstance(message.channel, discord.Thread):
                if message.channel.parent:
                    actual_channel_id = message.channel.parent.id

            channel_config = get_channel_config_by_discord_ids(
                db, guild_id, actual_channel_id
            )
            return guild_config, channel_config

    guild_config, channel_config = await asyncio.to_thread(_get_configs)

    if not guild_config:
        return ShouldRespondContext(
            should_respond=False, persona_id=None, thread_only_mode=False
        )

    # Only respond in channels that have an enabled channel config
    if not channel_config or not channel_config.enabled:
        return ShouldRespondContext(
            should_respond=False, persona_id=None, thread_only_mode=False
        )

    # Determine persona (channel override or guild default)
    persona_id = guild_config.default_persona_id
    if channel_config.persona_override_id is not None:
        persona_id = channel_config.persona_override_id

    # Check mention requirement (with exceptions)
    if channel_config.require_bot_invocation and not bot_mentioned:
        # Check for exceptions where we should respond without explicit mention
        should_respond_anyway = await check_implicit_invocation(message, bot_user)
        if not should_respond_anyway:
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
    bot_user: discord.User,
) -> bool:
    """Check if the bot should respond without explicit mention.

    Returns True if any of these conditions are met:
    1. User is replying to a bot message
    2. User is in a thread created from a bot message
    3. User is in a thread owned/created by the bot
    """
    logger.debug(f"Checking implicit invocation for message {message.id}")

    # 1. Check if replying to a bot message
    if message.reference and message.reference.message_id:
        logger.debug(
            f"Message has reference to message_id={message.reference.message_id}"
        )
        try:
            referenced_msg = await message.channel.fetch_message(
                message.reference.message_id
            )
            logger.debug(
                f"Referenced message author: {referenced_msg.author.id}, bot id: {bot_user.id}"
            )
            if referenced_msg.author.id == bot_user.id:
                logger.debug("Implicit invocation: user is replying to bot message")
                return True
        except (discord.NotFound, discord.HTTPException) as e:
            logger.debug(f"Failed to fetch referenced message: {e}")

    # 2 & 3. Check thread-related conditions
    if isinstance(message.channel, discord.Thread):
        thread = message.channel
        logger.debug(
            f"Message is in thread: id={thread.id}, name={thread.name}, "
            f"owner_id={thread.owner_id}, parent={thread.parent}, "
            f"parent_type={type(thread.parent).__name__ if thread.parent else None}"
        )

        # Check if thread is owned by the bot (bot created the thread)
        if thread.owner_id == bot_user.id:
            logger.debug("Implicit invocation: bot owns this thread")
            return True

        # Check if thread was created from a bot message
        # (thread.id equals the starter message id for threads created from messages)
        if thread.parent and not isinstance(thread.parent, discord.ForumChannel):
            logger.debug(
                f"Attempting to fetch starter message from parent channel, message_id={thread.id}"
            )
            try:
                starter_message = await thread.parent.fetch_message(thread.id)
                logger.debug(
                    f"Starter message found: id={starter_message.id}, "
                    f"author={starter_message.author.id}, "
                    f"content={starter_message.content[:100] if starter_message.content else '(empty)'}..."
                )
                if starter_message.author.id == bot_user.id:
                    logger.debug(
                        "Implicit invocation: thread created from bot's message"
                    )
                    return True
            except (discord.NotFound, discord.HTTPException) as e:
                logger.debug(f"Failed to fetch starter message: {e}")

    logger.debug("No implicit invocation detected")
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
    bot_user: discord.User,
) -> None:
    """Process a message and send response."""
    # Add thinking reaction
    try:
        await message.add_reaction(THINKING_EMOJI)
    except discord.DiscordException:
        logger.warning(f"Failed to add thinking reaction to message {message.id}")

    try:
        # Build thread context if in a thread
        thread_context = None
        forum_title = None
        if isinstance(message.channel, discord.Thread):
            logger.debug("Message is in a thread. Building thread context...")
            thread_context = await build_thread_context(message, bot_user)
            # Check if this is a forum post (thread with ForumChannel parent)
            if isinstance(message.channel.parent, discord.ForumChannel):
                forum_title = (
                    message.channel.name
                )  # Thread name is the forum post title

        # Prepare message content (format mentions to readable names)
        formatted_content = format_message_content(message)
        parts = []
        if thread_context:
            parts.append(thread_context)
        if forum_title:
            parts.append(f"Forum post title: {forum_title}")
        parts.append(f"Current message: {formatted_content}")
        content = "\n\n".join(parts)

        # Send to API
        response = await api_client.send_chat_message(
            message=content,
            api_key=api_key,
            persona_id=persona_id,
        )

        # Format and send response
        answer = (
            response.answer if response.answer else "I couldn't generate a response."
        )

        # Handle citations if present
        # CitationInfo only contains citation_number and document_id,
        # so we need to look up the actual document from top_documents
        if response.citation_info and response.top_documents:
            cited_docs: list[tuple[int, str, str | None]] = []
            for citation_info in response.citation_info:
                matching_doc = next(
                    (
                        d
                        for d in response.top_documents
                        if d.document_id == citation_info.document_id
                    ),
                    None,
                )
                if matching_doc:
                    cited_docs.append(
                        (
                            citation_info.citation_number,
                            matching_doc.semantic_identifier or "Source",
                            matching_doc.link,
                        )
                    )

            # Sort by citation number and limit to top 5
            cited_docs.sort(key=lambda x: x[0])
            if cited_docs:
                citations_text = "\n\n**Sources:**\n"
                for citation_num, doc_name, link in cited_docs[:5]:
                    if link:
                        # Wrap URL in angle brackets to suppress Discord embed previews
                        citations_text += f"{citation_num}. [{doc_name}](<{link}>)\n"
                    else:
                        citations_text += f"{citation_num}. {doc_name}\n"
                answer += citations_text

        # Split long messages
        await send_response(message, answer, thread_only_mode)

        # Update reaction to success
        try:
            await message.remove_reaction(THINKING_EMOJI, bot_user)
        except discord.DiscordException:
            pass

    except APIError as e:
        logger.error(f"API error processing message: {e}")
        await send_error_response(message, bot_user)
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        await send_error_response(message, bot_user)


# -------------------------------------------------------------------------
# Thread Context
# -------------------------------------------------------------------------


async def build_thread_context(
    message: discord.Message,
    bot_user: discord.User,
) -> str | None:
    """Build conversation context from thread history."""
    if not isinstance(message.channel, discord.Thread):
        return None

    try:
        thread = message.channel
        logger.debug(
            f"Building thread context for thread: id={thread.id}, name={thread.name}, "
            f"parent={thread.parent}, parent_type={type(thread.parent).__name__ if thread.parent else None}"
        )

        # Fetch most recent messages (excluding current)
        messages = []
        async for msg in thread.history(limit=20, oldest_first=False):
            if msg.id != message.id:
                messages.append(msg)

        logger.debug(
            f"Fetched {len(messages)} messages from thread history (excluding current)"
        )
        for msg in messages:
            logger.debug(
                f"  - msg_id={msg.id}, author={msg.author.display_name}, "
                f"type={msg.type}, content={msg.content[:50] if msg.content else '(empty)'}..."
            )

        # Also fetch the thread's starter message if not already included
        # This is important for threads created via Discord's "Create Thread" feature
        # For threads, the thread ID equals the starter message ID
        try:
            if thread.parent and not isinstance(thread.parent, discord.ForumChannel):
                logger.debug(
                    f"Attempting to fetch starter message from parent, message_id={thread.id}"
                )
                starter_message = await thread.parent.fetch_message(thread.id)
                logger.debug(
                    f"Starter message fetched: id={starter_message.id}, "
                    f"author={starter_message.author.display_name}, "
                    f"type={starter_message.type}, "
                    f"content={starter_message.content[:100] if starter_message.content else '(empty)'}..."
                )
                if starter_message and starter_message.id != message.id:
                    # Check if starter message is already in our list
                    already_in_list = any(m.id == starter_message.id for m in messages)
                    logger.debug(f"Starter message already in list: {already_in_list}")
                    if not already_in_list:
                        messages.append(starter_message)
                        logger.debug("Added starter message to context")
            else:
                logger.debug(
                    f"Skipping starter message fetch: parent={thread.parent}, "
                    f"is_forum={isinstance(thread.parent, discord.ForumChannel) if thread.parent else 'N/A'}"
                )
        except (discord.NotFound, discord.HTTPException) as e:
            # Starter message may not exist (e.g., deleted)
            logger.debug(f"Failed to fetch starter message: {e}")

        if not messages:
            logger.debug("No messages found for thread context")
            return None

        # Sort messages chronologically by ID (snowflake IDs are chronological)
        messages.sort(key=lambda m: m.id)

        logger.debug(f"Final thread context has {len(messages)} messages")

        # Format context
        formatted = []
        for msg in messages:
            # Non-default messages are usually server activities like user joined
            if msg.type != discord.MessageType.default:
                continue

            if msg.author.id == bot_user.id:
                sender = "OnyxBot"
            else:
                sender = f"@{msg.author.display_name}"

            # Format content with readable mentions
            content = format_message_content(msg)
            formatted.append(f"{sender}: {content}")

        if not formatted:
            return None

        context = "You are a Discord bot named OnyxBot.\n"
        context += "Conversation history:\n"
        context += "---\n"
        context += "\n".join(formatted)
        context += "\n---"

        return context

    except Exception as e:
        logger.warning(f"Failed to build thread context: {e}")
        return None


# -------------------------------------------------------------------------
# Message Formatting
# -------------------------------------------------------------------------


def format_message_content(message: discord.Message) -> str:
    """Format message content with readable user mentions.

    Replaces raw mentions like <@123456789> with @display_name.
    """
    content = message.content

    # Replace user mentions with display names
    for user in message.mentions:
        # Replace both <@ID> and <@!ID> formats (nickname mention)
        content = content.replace(f"<@{user.id}>", f"@{user.display_name}")
        content = content.replace(f"<@!{user.id}>", f"@{user.display_name}")

    # Replace role mentions with role names
    for role in message.role_mentions:
        content = content.replace(f"<@&{role.id}>", f"@{role.name}")

    # Replace channel mentions with channel names
    for channel in message.channel_mentions:
        content = content.replace(f"<#{channel.id}>", f"#{channel.name}")

    return content


# -------------------------------------------------------------------------
# Response Sending
# -------------------------------------------------------------------------


async def send_response(
    message: discord.Message,
    content: str,
    thread_only_mode: bool,
) -> None:
    """Send response based on thread_only_mode setting.

    If thread_only_mode is True:
        - If already in a thread, respond there
        - If in a channel, create a new thread from the message and respond there
    If thread_only_mode is False:
        - Reply directly to the message in the channel
    """
    # Split into chunks if too long
    chunks = split_message(content)

    if isinstance(message.channel, discord.Thread):
        # Already in a thread - always send directly there
        for chunk in chunks:
            await message.channel.send(chunk)
    elif thread_only_mode:
        # Create a thread from the user's message and respond there
        thread_name = f"OnyxBot <> {message.author.display_name}"
        # Truncate thread name if too long (Discord limit is 100 chars)
        if len(thread_name) > 100:
            thread_name = thread_name[:97] + "..."
        thread = await message.create_thread(name=thread_name)
        for chunk in chunks:
            await thread.send(chunk)
    else:
        # Reply directly in the channel
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)


def split_message(content: str) -> list[str]:
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
    bot_user: discord.User,
) -> None:
    """Send error response in a thread and update reaction.

    Note: Error details are logged server-side but not exposed to users.
    """
    try:
        await message.remove_reaction(THINKING_EMOJI, bot_user)
    except discord.DiscordException:
        pass

    error_msg = "Sorry, I encountered an error processing your message. You may want to contact Onyx for support :sweat_smile:"

    try:
        # Respond in thread (create one if needed)
        if isinstance(message.channel, discord.Thread):
            await message.channel.send(error_msg)
        else:
            thread = await message.create_thread(
                name=f"Response to {message.author.display_name}"[:100]
            )
            await thread.send(error_msg)
    except discord.DiscordException:
        pass
