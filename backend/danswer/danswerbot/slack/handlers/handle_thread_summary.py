from typing import Any
from typing import List

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from sqlalchemy.orm import Session

from danswer.connectors.slack.connector import get_thread
from danswer.danswerbot.slack.blocks import build_thread_summary_blocks
from danswer.danswerbot.slack.utils import (
    format_messages_for_summary,
)
from danswer.danswerbot.slack.utils import SlackTextCleaner
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.persona import get_persona_by_name
from danswer.llm.custom_llm import CustomModelServer
from danswer.llm.interfaces import LLM
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.prompts.chat_prompts import THREAD_SUMMARY_CHUNK_PROMPT
from danswer.prompts.chat_prompts import THREAD_SUMMARY_FINAL_PROMPT
from danswer.utils.logger import setup_logger
from danswer.utils.text_processing import chunk_text
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def summarize_chunk(
    chunk: str,
    llm: LLM,
    system_prompt: str | None = None,
    task_prompt: str | None = None,
) -> str:
    """Summarize a single chunk of messages in a concise way."""
    # Use provided system prompt or fall back to default
    if not system_prompt:
        system_prompt = THREAD_SUMMARY_CHUNK_PROMPT

    system_message = SystemMessage(content=system_prompt)
    # Use task prompt if available, otherwise use default prompt
    user_prompt = (
        task_prompt if task_prompt else "Summarize this Slack thread for quick reading:"
    )
    user_message = HumanMessage(content=f"{user_prompt}\n\n{chunk}")

    messages = [system_message, user_message]
    response = llm.invoke(messages)
    return response.content.strip()


def summarize_summaries(
    summaries: List[str],
    llm: LLM,
    system_prompt: str | None = None,
    task_prompt: str | None = None,
) -> str:
    """Combine and summarize multiple chunk summaries into a short final summary."""
    # Use provided system prompt or fall back to default
    if not system_prompt:
        system_prompt = THREAD_SUMMARY_FINAL_PROMPT

    combined_summaries = "\n\n".join(summaries)
    system_message = SystemMessage(content=system_prompt)

    # Use task prompt if available, otherwise use default prompt
    user_prompt = (
        task_prompt if task_prompt else "Combine these into a quick final summary:"
    )
    user_message = HumanMessage(content=f"{user_prompt}\n\n{combined_summaries}")

    messages = [system_message, user_message]
    response = llm.invoke(messages)
    return response.content.strip()


def handle_thread_summary(
    channel_id: str,
    thread_ts: str,
    client: Any,
    user_id: str,
    llm: LLM | None = None,
    is_parent_message: bool = False,
) -> None:
    """Handle the thread summarization shortcut."""
    if llm is None:
        # Initialize custom LLM with default values
        llm = CustomModelServer(
            api_key=None,
            timeout=30,  # 30 second timeout
        )

    messages = get_thread(client, channel_id, thread_ts)
    if not messages:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="No messages found in this thread.",
        )
        return

    # Get personas and their prompts for both summarization steps
    chunk_prompt = None
    chunk_task_prompt = None
    summary_prompt = None
    summary_task_prompt = None
    with Session(get_sqlalchemy_engine()) as db_session:
        chunk_persona = get_persona_by_name("Thread-Summary-Chunk", None, db_session)
        if chunk_persona and not chunk_persona.deleted and chunk_persona.prompts:
            chunk_prompt = chunk_persona.prompts[0].system_prompt
            chunk_task_prompt = chunk_persona.prompts[0].task_prompt

        summary_persona = get_persona_by_name("Thread-Summary-Final", None, db_session)
        if summary_persona and not summary_persona.deleted and summary_persona.prompts:
            summary_prompt = summary_persona.prompts[0].system_prompt
            summary_task_prompt = summary_persona.prompts[0].task_prompt

    # Format messages for summarization
    formatted_messages = format_messages_for_summary(messages, client)

    # Chunk the messages
    tokenizer = get_default_llm_tokenizer()
    chunks = chunk_text(
        formatted_messages,
        chunk_size=2000,
        tokenizer=tokenizer,
    )

    # Summarize each chunk in parallel
    chunk_summaries = run_functions_tuples_in_parallel(
        [
            (summarize_chunk, (chunk, llm, chunk_prompt, chunk_task_prompt))
            for chunk in chunks
        ]
    )

    # Combine and summarize the summaries
    final_summary = summarize_summaries(
        chunk_summaries, llm, summary_prompt, summary_task_prompt
    )

    # Process the summary to add clickable links
    processed_summary = ""
    for line in final_summary.split("\n"):
        # Find the last occurrence of square brackets
        start_idx = line.rfind("[")
        end_idx = line.rfind("]")
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            timestamp = line[start_idx + 1 : end_idx]
            # Remove 'ts:' prefix if it exists
            if timestamp.startswith("ts:"):
                timestamp = timestamp[3:]
            # Verify that the content is actually numeric (a valid timestamp)
            if timestamp.replace(".", "").isdigit():
                try:
                    permalink = client.chat_getPermalink(
                        channel=channel_id,
                        message_ts=timestamp,
                    )
                    # Replace the timestamp with a clickable link
                    line = (
                        line[:start_idx]
                        + f"<{permalink.data['permalink']}|[View Message]>"
                        + line[end_idx + 1 :]
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to create permalink for timestamp {timestamp}: {e}"
                    )
                    # Remove the timestamp and its brackets when permalink creation fails
                    line = line[:start_idx] + line[end_idx + 1 :]
        processed_summary += line + "\n"

    text_cleaner = SlackTextCleaner(client)

    # Handle bold syntax for Slack
    processed_summary = text_cleaner.handle_bold_syntax_for_slack(processed_summary)

    try:
        # Get the thread starter's name from the first message
        thread_starter_id = messages[0].get("user")
        user_name = text_cleaner._get_slack_name(thread_starter_id)
    except Exception:
        user_name = thread_starter_id if thread_starter_id else "Unknown"

    # Build the summary blocks
    blocks = build_thread_summary_blocks(
        summary=processed_summary.strip(),
        user_name=user_name,
    )

    # If triggered from parent message, post as a hidden message in the channel
    if is_parent_message:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=blocks,
            text=f"Thread Summary: {final_summary[:100]}..."
            if len(final_summary) > 100
            else f"Thread Summary: {final_summary}",
        )
    else:
        # Post as a hidden message in the thread
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=blocks,
            thread_ts=thread_ts,
            text=f"Thread Summary: {final_summary[:100]}..."
            if len(final_summary) > 100
            else f"Thread Summary: {final_summary}",
        )
