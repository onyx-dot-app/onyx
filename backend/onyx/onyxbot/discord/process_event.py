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


def get_thread_messages(message: discord.Message) -> list[ThreadMessage]:
    messages = []
    if isinstance(message.channel, discord.Thread):
        messages.append(
            ThreadMessage(
                message=message.content,
                sender=str(message.author),
                role=MessageType.USER,
            )
        )
    else:
        messages.append(
            ThreadMessage(
                message=message.content,
                sender=str(message.author),
                role=MessageType.USER,
            )
        )
    return messages


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
) -> None:
    channel = message.channel
    thread = None

    try:
        await update_emote_react(
            channel,
            message,
            ":thinking:",
        )

        if message_info.thread_messages[-1].message in _DISCORD_GREETINGS_TO_IGNORE:
            return

        # Create thread title from the question
        thread_name = message.content
        # Remove bot mention if present
        if bot.user in message.mentions:
            thread_name = thread_name.replace(f"<@{bot.user.id}>", "").strip()
        # Truncate and provide fallback
        thread_name = thread_name[:100] if thread_name else "New conversation"

        content = message_info.thread_messages[-1].message
        if DANSWER_BOT_REPHRASE_MESSAGE:
            try:
                content = rephrase_slack_message(content)
            except Exception as e:
                logger.error(f"Error rephrasing message: {e}")

        with get_session_with_tenant(message_info.tenant_id) as db_session:
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

            try:
                generator = stream_chat_message_objects(
                    answer_request,
                    user=None,
                    db_session=db_session,
                )
                answer = ""
                documents = []

                for chunk in generator:
                    if isinstance(chunk, StreamingError):
                        raise Exception(f"Error getting answer from LLM: {chunk.error}")

                    if hasattr(chunk, "answer_piece"):
                        answer += chunk.answer_piece

                    if hasattr(chunk, "context_docs"):
                        if hasattr(chunk.context_docs, "top_documents"):
                            for doc in chunk.context_docs.top_documents:
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
                                documents.append(doc)

                if not answer.strip():
                    raise Exception("No response content generated")

                # Truncate answer if it's too long
                if len(answer) > 2000:
                    logger.warning(
                        f"Answer exceeded 2000 chars, truncating. Original length: {len(answer)}"
                    )
                    answer = answer[:1997] + "..."

                # Get channel config to check for citations requirement
                channel_config = get_discord_channel_config_for_bot_and_channel(
                    db_session=db_session,
                    discord_bot_id=bot.discord_bot_id,
                    channel_name=channel.name,
                )

                config = channel_config.channel_config if channel_config else {}
                answer_filters = config.get("answer_filters", [])
                require_citations = "well_answered_postfilter" in answer_filters

                # Check citations requirement after getting the answer
                if (
                    require_citations
                    and not message_info.bypass_filters
                    and not documents
                ):
                    await message.reply(
                        "I couldn't find any relevant citations to support an answer. Please try rephrasing your question.",
                        ephemeral=True,
                    )
                    return

                embeds = []
                if documents:
                    doc_embed = discord.Embed(
                        title="Reference Documents", color=0x00FF00
                    )

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
                        source_type = str(doc.source_type).replace(
                            "DocumentSource.", ""
                        )
                        value_parts.append(f"Source: {source_type}")

                        if doc.updated_at:
                            time_ago = timeago.format(
                                doc.updated_at, datetime.now(timezone.utc)
                            )
                            value_parts.append(f"Updated {time_ago}")

                        if doc.primary_owners and len(doc.primary_owners) > 0:
                            value_parts.append(f"By {doc.primary_owners[0]}")

                        if doc.link:
                            value_parts.append(f"[View Document]({doc.link})")

                        if doc.match_highlights:
                            highlights = [
                                h.strip(" .") for h in doc.match_highlights if h.strip()
                            ]
                            if highlights:
                                highlight = highlights[0]
                                highlight = " ".join(highlight.split())
                                highlight = highlight.replace("<hi>", "**").replace(
                                    "</hi>", "**"
                                )
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

                    embeds.append(doc_embed)

                # Get channel config for follow-up tags
                channel_config = get_discord_channel_config_for_bot_and_channel(
                    db_session=db_session,
                    discord_bot_id=bot.discord_bot_id,
                    channel_name=channel.name,
                )

                # Get the follow-up tags from channel config
                follow_up_tags = (
                    channel_config.channel_config.get("follow_up_tags")
                    if channel_config
                    else None
                )

                # First get the chat message ID from the database
                with get_session_with_tenant(message_info.tenant_id) as db_session:
                    stmt = (
                        select(ChatMessage)
                        .where(
                            ChatMessage.message == answer,
                            ChatMessage.message_type == MessageType.ASSISTANT,
                        )
                        .order_by(ChatMessage.time_sent.desc())
                    )

                    chat_message = db_session.execute(stmt).first()

                # Create views with the database message ID
                feedback_view = FeedbackView(
                    message_id=chat_message[0].id
                    if chat_message
                    else 0,  # Use database ID
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

                # Determine where to send messages
                target_channel = channel
                if not isinstance(channel, discord.Thread):
                    thread = await message.create_thread(
                        name=thread_name, auto_archive_duration=1440
                    )
                    target_channel = thread

                # Send the main response
                await target_channel.send(content=answer, view=combined_view)

                with get_session_with_tenant(message_info.tenant_id) as db_session:
                    stmt = (
                        select(ChatMessage)
                        .where(
                            ChatMessage.message == answer,
                            ChatMessage.message_type == MessageType.ASSISTANT,
                        )
                        .order_by(ChatMessage.time_sent.desc())
                    )

                    chat_message = db_session.execute(stmt).first()
                    if chat_message:
                        # Get channel config and check if we should show the continue button
                        channel_config = get_discord_channel_config_for_bot_and_channel(
                            db_session=db_session,
                            discord_bot_id=bot.discord_bot_id,
                            channel_name=channel.name,
                        )

                        if isinstance(channel, discord.DMChannel) or (
                            channel_config
                            and channel_config.channel_config.get(
                                "show_continue_in_web_ui", False
                            )
                        ):
                            continue_view = ContinueOnOnyxView(
                                chat_session_id=str(chat_message[0].chat_session_id),
                                tenant_id=message_info.tenant_id,
                            )
                            await target_channel.send(view=continue_view)

                # Send reference documents in the same thread/channel
                if embeds:
                    doc_view = DocumentFeedbackView(
                        document_id=str(documents[0].document_id),
                        tenant_id=message_info.tenant_id,
                    )
                    await target_channel.send(embeds=embeds, view=doc_view)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

                await update_emote_react(
                    channel,
                    message,
                    ":thinking:",
                    remove=True,
                )
                await update_emote_react(
                    channel,
                    message,
                    ":white_check_mark:",
                )

            except Exception:
                await message.reply(
                    "I apologize, but I encountered an error while processing your request. Please try again later."
                )
                return

    except Exception:
        await message.reply(
            "I apologize, but I encountered an error while processing your request. Please try again later."
        )


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
        logger.info(f"Getting session with tenant: {message_info.tenant_id}")
        with get_session_with_tenant(message_info.tenant_id) as db_session:
            # Skip channel config check for DMs
            if isinstance(message.channel, discord.DMChannel):
                await handle_regular_answer(message, message_info, bot)
                return
            channel_config = get_discord_channel_config_for_bot_and_channel(
                db_session=db_session,
                discord_bot_id=bot.discord_bot_id,
                channel_name=message.channel.name,
            )
            should_process = await should_process_message(message, channel_config, bot)
            if not should_process:
                return

            await handle_regular_answer(message, message_info, bot)
    except Exception:
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
        except Exception:
            logger.exception("Failed to process discord event")

    return process_discord_event
