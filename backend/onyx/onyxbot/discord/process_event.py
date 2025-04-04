from datetime import datetime
from datetime import timezone

import discord
import timeago
from discord.ext import commands
from sqlalchemy import select

from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import StreamingError
from onyx.chat.models import ThreadMessage
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.constants import MessageType
from onyx.configs.onyxbot_configs import DANSWER_BOT_NUM_DOCS_TO_DISPLAY
from onyx.configs.onyxbot_configs import DANSWER_BOT_REPHRASE_MESSAGE
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import OptionalSearchSetting
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import DiscordChannelConfig
from onyx.onyxbot.discord.config import get_discord_channel_config_for_bot_and_channel
from onyx.onyxbot.discord.models import DiscordMessageInfo
from onyx.onyxbot.discord.utils import update_emote_react
from onyx.onyxbot.discord.views import ContinueOnOnyxView
from onyx.onyxbot.discord.views import DocumentFeedbackView
from onyx.onyxbot.discord.views import FeedbackView
from onyx.onyxbot.discord.views import StillNeedHelpView
from onyx.onyxbot.slack.utils import rephrase_slack_message
from onyx.utils.logger import setup_logger

logger = setup_logger()

# In rare cases, some users have been experiencing a massive amount of trivial messages
# Adding this to avoid exploding LLM costs while we track down the cause.
_DISCORD_GREETINGS_TO_IGNORE = {
    "Welcome back!",
    "It's going to be a great day.",
    "Salutations!",
    "Greetings!",
    "Feeling great!",
    "Hi there",
    ":wave:",
}


def prefilter_message(message: discord.Message) -> bool:
    """Filter out messages that shouldn't be processed"""
    if not message.content:
        logger.warning("Cannot respond to empty message - skipping")
        return False
    if message.author.bot:
        logger.info("Ignoring message from bot")
        return False
    if message.content in _DISCORD_GREETINGS_TO_IGNORE:
        logger.error(f"Ignoring greeting message: '{message.content}'")
        return False
    return True


def build_message_info(
    message: discord.Message,
    bot: commands.Bot,
) -> DiscordMessageInfo:
    # Check if bot was mentioned or if it's a DM
    is_bot_mention = bot.user in message.mentions
    is_dm = isinstance(message.channel, discord.DMChannel)

    # Get message content, removing bot mention if present
    content = message.content
    if is_bot_mention:
        content = content.replace(f"<@{bot.user.id}>", "").strip()

    # Get channel and thread IDs
    str(message.channel.id)
    thread_id = str(message.thread.id) if message.thread else None

    # Build thread messages
    thread_messages = [
        ThreadMessage(
            message=content,
            message_type=MessageType.USER,
            message_id=str(message.id),
        )
    ]

    return DiscordMessageInfo(
        tenant_id=bot.tenant_id,
        thread_messages=thread_messages,
        channel_to_respond=str(message.channel.id),
        msg_to_respond=str(message.id),
        thread_to_respond=thread_id,
        bypass_filters=is_bot_mention or is_dm,
        is_bot_msg=message.author.bot,
        is_bot_dm=is_dm,
        sender_id=str(message.author.id),
        email=f"{message.author.id}@discord.com",
        chat_session_id=str(message.id),
    )


async def handle_regular_answer(
    message: discord.Message,
    message_info: DiscordMessageInfo,
    bot: commands.Bot,
    db_session,
    channel_config: DiscordChannelConfig | None = None,
) -> None:
    channel = message.channel

    try:
        await update_emote_react(channel, message, ":thinking:")

        if message_info.thread_messages[-1].message in _DISCORD_GREETINGS_TO_IGNORE:
            logger.info(
                f"Skipping greeting message: {message_info.thread_messages[-1].message}"
            )
            return

        thread_name = _create_thread_name(message, bot)
        content = _prepare_message_content(message_info)

        answer, documents = await _get_answer_and_documents(
            content, message_info, db_session
        )

        if not answer.strip():
            logger.error("LLM generated empty response for message: %s", content[:100])
            raise Exception("No response content generated")

        # Truncate answer if it's too long
        if len(answer) > 2000:
            logger.warning(
                "Answer exceeded Discord's 2000 char limit. Original length: %d, content preview: %s...",
                len(answer),
                answer[:100],
            )
            answer = answer[:1997] + "..."

        # Check if citations are required
        if not await _check_citations_requirement(
            channel_config, message_info, documents, message
        ):
            logger.info(
                "Citations required but none found. Channel: %s, Message: %s",
                channel.name if hasattr(channel, "name") else "DM",
                content[:100],
            )
            return

        embeds = _create_document_embeds(documents) if documents else []

        # Get the chat message ID from the database
        chat_message = _get_chat_message(db_session, message_info.tenant_id, answer)
        if not chat_message:
            logger.warning(
                "Could not find chat message in database for tenant %s, answer preview: %s...",
                message_info.tenant_id,
                answer[:100],
            )

        # Create views and send response
        target_channel = await _prepare_target_channel(channel, message, thread_name)

        # Extract config values once
        config = channel_config.channel_config if channel_config else {}
        follow_up_tags = config.get("follow_up_tags")
        show_continue = (
            config.get("show_continue_in_web_ui", False) if channel_config else False
        )

        await _send_response_with_views(
            target_channel=target_channel,
            answer=answer,
            embeds=embeds,
            chat_message=chat_message,
            message_info=message_info,
            follow_up_tags=follow_up_tags,
            show_continue=show_continue,
            channel=channel,
            documents=documents,
        )

        await update_emote_react(channel, message, ":thinking:", remove=True)
        await update_emote_react(channel, message, ":white_check_mark:")

    except Exception as e:
        logger.exception(
            "Failed to process message. Channel: %s, Content: %s, Error: %s",
            channel.name if hasattr(channel, "name") else "DM",
            message.content[:100],
            str(e),
        )
        await message.reply(
            "I apologize, but I encountered an error while processing your request. Please try again later."
        )


def _create_thread_name(message: discord.Message, bot: commands.Bot) -> str:
    """Create a thread name from the message content"""
    thread_name = message.content
    # Remove bot mention if present
    if bot.user in message.mentions:
        thread_name = thread_name.replace(f"<@{bot.user.id}>", "").strip()
    # Truncate and provide fallback
    return thread_name[:100] if thread_name else "New conversation"


def _prepare_message_content(message_info: DiscordMessageInfo) -> str:
    """Prepare the message content, potentially rephrasing it"""
    content = message_info.thread_messages[-1].message
    if DANSWER_BOT_REPHRASE_MESSAGE:
        try:
            content = rephrase_slack_message(content)
        except Exception as e:
            logger.error(f"Error rephrasing message: {e}")
    return content


async def _get_answer_and_documents(
    content: str, message_info: DiscordMessageInfo, db_session
) -> tuple[str, list]:
    """Get answer and documents from the LLM"""
    try:
        answer_request = prepare_chat_message_request(
            message_text=content,
            user=None,
            persona_id=None,
            persona_override_config=None,
            prompt=None,
            message_ts_to_respond_to=message_info.msg_to_respond,
            retrieval_details=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
                filters=BaseFilters(),
                enable_auto_detect_filters=True,
            ),
            rerank_settings=None,
            db_session=db_session,
        )

        generator = stream_chat_message_objects(
            answer_request,
            user=None,
            db_session=db_session,
        )

        answer = ""
        documents = []

        for chunk in generator:
            if isinstance(chunk, StreamingError):
                logger.error(
                    "Error in LLM response streaming. Message: %s, Error: %s",
                    content[:100],
                    chunk.error,
                )
                raise Exception(f"Error getting answer from LLM: {chunk.error}")

            if hasattr(chunk, "answer_piece"):
                answer += chunk.answer_piece

            if hasattr(chunk, "context_docs"):
                if hasattr(chunk.context_docs, "top_documents"):
                    documents.extend(
                        _filter_documents(chunk.context_docs.top_documents)
                    )

        return answer, documents
    except Exception as e:
        logger.exception(
            "Failed to get answer from LLM. Content: %s, Error: %s",
            content[:100],
            str(e),
        )
        raise


def _filter_documents(docs):
    """Filter out internal documents"""
    filtered_docs = []
    for doc in docs:
        if any(
            onyx_doc in doc.semantic_identifier.lower()
            for onyx_doc in [
                "customer support",
                "enterprise search",
                "operations",
                "ai platform",
                "sales",
                "use cases",
            ]
        ):
            continue
        filtered_docs.append(doc)
    return filtered_docs


async def _check_citations_requirement(
    channel_config, message_info, documents, message
) -> bool:
    """Check if citations are required and if we have them"""
    if not channel_config:
        return True

    config = channel_config.channel_config if channel_config else {}
    answer_filters = config.get("answer_filters", [])
    require_citations = "well_answered_postfilter" in answer_filters

    if require_citations and not message_info.bypass_filters and not documents:
        await message.reply(
            "I couldn't find any relevant citations to support an answer. Please try rephrasing your question.",
            ephemeral=True,
        )
        return False
    return True


def _create_document_embeds(documents) -> list:
    """Create Discord embeds for the documents"""
    if not documents:
        return []

    doc_embed = discord.Embed(title="Reference Documents", color=0x00FF00)
    seen_docs_identifiers = set()
    included_docs = 0

    for doc in documents:
        if doc.document_id in seen_docs_identifiers:
            continue
        seen_docs_identifiers.add(doc.document_id)

        title = doc.semantic_identifier[:70]
        if len(doc.semantic_identifier) > 70:
            title += "..."

        value_parts = []
        source_type = str(doc.source_type).replace("DocumentSource.", "")
        value_parts.append(f"Source: {source_type}")

        if doc.updated_at:
            time_ago = timeago.format(doc.updated_at, datetime.now(timezone.utc))
            value_parts.append(f"Updated {time_ago}")

        if doc.primary_owners and len(doc.primary_owners) > 0:
            value_parts.append(f"By {doc.primary_owners[0]}")

        if doc.link:
            value_parts.append(f"[View Document]({doc.link})")

        if doc.match_highlights:
            highlights = [h.strip(" .") for h in doc.match_highlights if h.strip()]
            if highlights:
                highlight = highlights[0]
                highlight = " ".join(highlight.split())
                highlight = highlight.replace("<hi>", "**").replace("</hi>", "**")
                if len(highlight) > 300:
                    highlight = highlight[:297] + "..."
                value_parts.append(f"\nRelevant excerpt:\n{highlight}")

        field_value = "\n".join(value_parts)
        if len(field_value) > 1024:
            field_value = field_value[:1021] + "..."

        doc_embed.add_field(
            name=title,
            value=field_value or "No preview available",
            inline=False,
        )

        included_docs += 1
        if included_docs >= DANSWER_BOT_NUM_DOCS_TO_DISPLAY:
            break

    return [doc_embed]


def _get_chat_message(db_session, tenant_id, answer):
    """Get the chat message from the database"""
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.message == answer,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .order_by(ChatMessage.time_sent.desc())
    )
    return db_session.execute(stmt).first()


async def _prepare_target_channel(channel, message, thread_name):
    """Prepare the target channel or thread for sending the response"""
    if not isinstance(channel, discord.Thread):
        thread = await message.create_thread(
            name=thread_name, auto_archive_duration=1440
        )
        return thread
    return channel


async def _send_response_with_views(
    target_channel,
    answer,
    embeds,
    chat_message,
    message_info,
    follow_up_tags,
    show_continue,
    channel,
    documents,
):
    """Send the response with appropriate views"""
    # Create views with the database message ID
    feedback_view = FeedbackView(
        message_id=chat_message[0].id if chat_message else 0,
        tenant_id=message_info.tenant_id,
        users_to_tag=follow_up_tags,
    )
    still_need_help_view = StillNeedHelpView(users_to_tag=follow_up_tags)

    # Combine views
    combined_view = discord.ui.View()
    for item in feedback_view.children:
        combined_view.add_item(item)
    for item in still_need_help_view.children:
        combined_view.add_item(item)

    # Send the main response
    await target_channel.send(content=answer, view=combined_view)

    # Check if we should show the continue button
    if chat_message and (isinstance(channel, discord.DMChannel) or show_continue):
        continue_view = ContinueOnOnyxView(
            chat_session_id=str(chat_message[0].chat_session_id),
            tenant_id=message_info.tenant_id,
        )
        await target_channel.send(view=continue_view)

    # Send reference documents in the same thread/channel
    if embeds and documents:
        doc_view = DocumentFeedbackView(
            document_id=str(documents[0].document_id),
            tenant_id=message_info.tenant_id,
        )
        await target_channel.send(embeds=embeds, view=doc_view)


async def should_process_message(
    message: discord.Message,
    channel_config: DiscordChannelConfig | None,
    bot: commands.Bot,
) -> bool:
    # Basic message filtering
    if not prefilter_message(message):
        return False

    # Always respond to DMs
    if isinstance(message.channel, discord.DMChannel):
        return True

    # No config - don't respond at all
    if not channel_config:
        return False

    config = channel_config.channel_config

    # Check question mark filter
    if (
        "answer_filters" in config
        and "questionmark_prefilter" in config["answer_filters"]
        and "?" not in message.content
    ):
        return False

    # Bot response handling
    if message.author.bot and not config.get("respond_to_bots", False):
        return False

    # Mention-only mode
    if config.get("respond_mention_only", False):
        return bot.user in message.mentions

    # Check member/group permissions
    allowed_members = config.get("respond_member_group_list", [])
    if allowed_members:
        user_id = message.author.name
        if user_id not in allowed_members:
            return False

    return True


async def process_message(
    message: discord.Message, message_info: DiscordMessageInfo, bot: commands.Bot
) -> None:
    if message.author == bot.user:
        return

    try:
        logger.info(
            "Processing message. Tenant: %s, Channel: %s, Author: %s",
            message_info.tenant_id,
            message.channel.name if hasattr(message.channel, "name") else "DM",
            message.author.name,
        )

        with get_session_with_tenant(message_info.tenant_id) as db_session:
            # Skip channel config check for DMs
            channel_config = None
            if not isinstance(message.channel, discord.DMChannel):
                # Get channel config once and reuse
                channel_config = get_discord_channel_config_for_bot_and_channel(
                    db_session=db_session,
                    discord_bot_id=bot.discord_bot_id,
                    channel_name=message.channel.name,
                )
                should_process = await should_process_message(
                    message, channel_config, bot
                )
                if not should_process:
                    logger.info(
                        "Skipping message processing due to filters. Channel: %s, Content: %s",
                        message.channel.name,
                        message.content[:100],
                    )
                    return

            await handle_regular_answer(
                message, message_info, bot, db_session, channel_config
            )
    except Exception as e:
        logger.exception(
            "Failed to process message. Channel: %s, Author: %s, Content: %s, Error: %s",
            message.channel.name if hasattr(message.channel, "name") else "DM",
            message.author.name,
            message.content[:100],
            str(e),
        )
        await message.reply(
            "I encountered an error processing your message. Please try again later."
        )


def create_process_discord_event():
    """Creates the main event processing function"""

    async def process_discord_event(message: discord.Message) -> None:
        try:
            await process_message(
                message,
                message.guild.me
                if message.guild
                else message.author.mutual_guilds[0].me,
            )
        except Exception as e:
            logger.exception(
                "Critical failure in discord event processing. Channel: %s, Author: %s, Content: %s, Error: %s",
                message.channel.name if hasattr(message.channel, "name") else "DM",
                message.author.name,
                message.content[:100],
                str(e),
            )

    return process_discord_event
