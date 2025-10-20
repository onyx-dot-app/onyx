from datetime import datetime
from typing import cast

import pytz
import timeago  # type: ignore
from slack_sdk.models.blocks import ActionsBlock
from slack_sdk.models.blocks import Block
from slack_sdk.models.blocks import ButtonElement
from slack_sdk.models.blocks import ContextBlock
from slack_sdk.models.blocks import DividerBlock
from slack_sdk.models.blocks import HeaderBlock
from slack_sdk.models.blocks import Option
from slack_sdk.models.blocks import RadioButtonsElement
from slack_sdk.models.blocks import SectionBlock
from slack_sdk.models.blocks.basic_components import MarkdownTextObject
from slack_sdk.models.blocks.block_elements import ImageElement

from onyx.chat.models import ChatBasicResponse
from onyx.configs.app_configs import DISABLE_GENERATIVE_AI
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import SearchFeedbackType
from onyx.configs.onyxbot_configs import ONYX_BOT_NUM_DOCS_TO_DISPLAY
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import get_chat_session_by_message_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChannelConfig
from onyx.onyxbot.slack.constants import CONTINUE_IN_WEB_UI_ACTION_ID
from onyx.onyxbot.slack.constants import DISLIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import FOLLOWUP_BUTTON_ACTION_ID
from onyx.onyxbot.slack.constants import FOLLOWUP_BUTTON_RESOLVED_ACTION_ID
from onyx.onyxbot.slack.constants import IMMEDIATE_RESOLVED_BUTTON_ACTION_ID
from onyx.onyxbot.slack.constants import KEEP_TO_YOURSELF_ACTION_ID
from onyx.onyxbot.slack.constants import LIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import SHOW_EVERYONE_ACTION_ID
from onyx.onyxbot.slack.formatting import format_slack_message
from onyx.onyxbot.slack.icons import source_to_github_img_link
from onyx.onyxbot.slack.models import ActionValuesEphemeralMessage
from onyx.onyxbot.slack.models import ActionValuesEphemeralMessageChannelConfig
from onyx.onyxbot.slack.models import ActionValuesEphemeralMessageMessageInfo
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import build_continue_in_web_ui_id
from onyx.onyxbot.slack.utils import build_feedback_id
from onyx.onyxbot.slack.utils import build_publish_ephemeral_message_id
from onyx.onyxbot.slack.utils import remove_slack_text_interactions
from onyx.onyxbot.slack.utils import translate_vespa_highlight_to_slack
from onyx.utils.text_processing import decode_escapes

_MAX_BLURB_LEN = 45


def _format_doc_updated_at(updated_at: datetime | None) -> str | None:
    """Convert document timestamps to a human friendly relative string."""
    if updated_at is None:
        return None

    if updated_at.tzinfo is None or updated_at.tzinfo.utcoffset(updated_at) is None:
        aware_updated_at = updated_at.replace(tzinfo=pytz.utc)
    else:
        aware_updated_at = updated_at.astimezone(pytz.utc)

    return timeago.format(aware_updated_at, datetime.now(pytz.utc))


def get_feedback_reminder_blocks(thread_link: str, include_followup: bool) -> Block:
    text = (
        f"Please provide feedback on <{thread_link}|this answer>. "
        "This is essential to help us to improve the quality of the answers. "
        "Please rate it by clicking the `Helpful` or `Not helpful` button. "
    )
    if include_followup:
        text += "\n\nIf you need more help, click the `I need more help from a human!` button. "

    text += "\n\nThanks!"

    return SectionBlock(text=text)


def _split_text(text: str, limit: int = 3000) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Find the nearest space before the limit to avoid splitting a word
        split_at = text.rfind(" ", 0, limit)
        if split_at == -1:  # No spaces found, force split
            split_at = limit

        chunk = text[:split_at]
        chunks.append(chunk)
        text = text[split_at:].lstrip()  # Remove leading spaces from the next chunk

    return chunks


def _clean_markdown_link_text(text: str) -> str:
    # Remove any newlines within the text
    return format_slack_message(text).replace("\n", " ").strip()


def _build_qa_feedback_block(
    message_id: int, feedback_reminder_id: str | None = None
) -> Block:
    return ActionsBlock(
        block_id=build_feedback_id(message_id),
        elements=[
            ButtonElement(
                action_id=LIKE_BLOCK_ACTION_ID,
                text="👍 Helpful",
                value=feedback_reminder_id,
            ),
            ButtonElement(
                action_id=DISLIKE_BLOCK_ACTION_ID,
                text="👎 Not helpful",
                value=feedback_reminder_id,
            ),
        ],
    )


def _build_ephemeral_publication_block(
    channel_id: str,
    chat_message_id: int,
    message_info: SlackMessageInfo,
    original_question_ts: str,
    channel_conf: ChannelConfig,
    feedback_reminder_id: str | None = None,
) -> Block:
    # check whether the message is in a thread
    if (
        message_info is not None
        and message_info.msg_to_respond is not None
        and message_info.thread_to_respond is not None
        and (message_info.msg_to_respond == message_info.thread_to_respond)
    ):
        respond_ts = None
    else:
        respond_ts = original_question_ts

    action_values_ephemeral_message_channel_config = (
        ActionValuesEphemeralMessageChannelConfig(
            channel_name=channel_conf.get("channel_name"),
            respond_tag_only=channel_conf.get("respond_tag_only"),
            respond_to_bots=channel_conf.get("respond_to_bots"),
            is_ephemeral=channel_conf.get("is_ephemeral", False),
            respond_member_group_list=channel_conf.get("respond_member_group_list"),
            answer_filters=channel_conf.get("answer_filters"),
            follow_up_tags=channel_conf.get("follow_up_tags"),
            show_continue_in_web_ui=channel_conf.get("show_continue_in_web_ui", False),
        )
    )

    action_values_ephemeral_message_message_info = (
        ActionValuesEphemeralMessageMessageInfo(
            bypass_filters=message_info.bypass_filters,
            channel_to_respond=message_info.channel_to_respond,
            msg_to_respond=message_info.msg_to_respond,
            email=message_info.email,
            sender_id=message_info.sender_id,
            thread_messages=[],
            is_slash_command=message_info.is_slash_command,
            is_bot_dm=message_info.is_bot_dm,
            thread_to_respond=respond_ts,
        )
    )

    action_values_ephemeral_message = ActionValuesEphemeralMessage(
        original_question_ts=original_question_ts,
        feedback_reminder_id=feedback_reminder_id,
        chat_message_id=chat_message_id,
        message_info=action_values_ephemeral_message_message_info,
        channel_conf=action_values_ephemeral_message_channel_config,
    )

    return ActionsBlock(
        block_id=build_publish_ephemeral_message_id(original_question_ts),
        elements=[
            ButtonElement(
                action_id=SHOW_EVERYONE_ACTION_ID,
                text="📢 Share with Everyone",
                value=action_values_ephemeral_message.model_dump_json(),
            ),
            ButtonElement(
                action_id=KEEP_TO_YOURSELF_ACTION_ID,
                text="🤫  Keep to Yourself",
                value=action_values_ephemeral_message.model_dump_json(),
            ),
        ],
    )


def get_document_feedback_blocks() -> Block:
    return SectionBlock(
        text=(
            "- 'Up-Boost' if this document is a good source of information and should be "
            "shown more often.\n"
            "- 'Down-boost' if this document is a poor source of information and should be "
            "shown less often.\n"
            "- 'Hide' if this document is deprecated and should never be shown anymore."
        ),
        accessory=RadioButtonsElement(
            options=[
                Option(
                    text=":thumbsup: Up-Boost",
                    value=SearchFeedbackType.ENDORSE.value,
                ),
                Option(
                    text=":thumbsdown: Down-Boost",
                    value=SearchFeedbackType.REJECT.value,
                ),
                Option(
                    text=":x: Hide",
                    value=SearchFeedbackType.HIDE.value,
                ),
            ]
        ),
    )


def _build_doc_feedback_block(
    message_id: int,
    document_id: str,
    document_rank: int,
) -> ButtonElement:
    feedback_id = build_feedback_id(message_id, document_id, document_rank)
    return ButtonElement(
        action_id=FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID,
        value=feedback_id,
        text="Give Feedback",
    )


def get_restate_blocks(
    msg: str,
    is_slash_command: bool,
) -> list[Block]:
    # Only the slash command needs this context because the user doesn't see their own input
    if not is_slash_command:
        return []

    return [
        HeaderBlock(text="Responding to the Query"),
        SectionBlock(text=f"```{msg}```"),
    ]


def _build_documents_blocks(
    documents: list[SavedSearchDoc],
    message_id: int | None,
    num_docs_to_display: int = ONYX_BOT_NUM_DOCS_TO_DISPLAY,
) -> list[Block]:
    header_text = (
        "Retrieved Documents" if DISABLE_GENERATIVE_AI else "Reference Documents"
    )
    seen_docs_identifiers = set()
    section_blocks: list[Block] = [HeaderBlock(text=header_text)]
    included_docs = 0
    for rank, d in enumerate(documents):
        if d.document_id in seen_docs_identifiers:
            continue
        seen_docs_identifiers.add(d.document_id)

        # Strip newlines from the semantic identifier for Slackbot formatting
        doc_sem_id = d.semantic_identifier.replace("\n", " ")
        if d.source_type == DocumentSource.SLACK.value:
            doc_sem_id = "#" + doc_sem_id

        used_chars = len(doc_sem_id) + 3
        match_str = translate_vespa_highlight_to_slack(d.match_highlights, used_chars)

        included_docs += 1

        header_line = f"{doc_sem_id}\n"
        if d.link:
            header_line = f"<{d.link}|{doc_sem_id}>\n"

        updated_at_line = ""
        updated_at_str = _format_doc_updated_at(d.updated_at)
        if updated_at_str:
            updated_at_line = f"_Updated {updated_at_str}_\n"

        body_text = f">{remove_slack_text_interactions(match_str)}"

        block_text = header_line + updated_at_line + body_text

        feedback: ButtonElement | dict = {}
        if message_id is not None:
            feedback = _build_doc_feedback_block(
                message_id=message_id,
                document_id=d.document_id,
                document_rank=rank,
            )

        section_blocks.append(
            SectionBlock(text=block_text, accessory=feedback),
        )

        section_blocks.append(DividerBlock())

        if included_docs >= num_docs_to_display:
            break

    return section_blocks


def _build_sources_blocks(
    cited_documents: list[tuple[int, SavedSearchDoc]],
    num_docs_to_display: int = ONYX_BOT_NUM_DOCS_TO_DISPLAY,
) -> list[Block]:
    if not cited_documents:
        return [
            SectionBlock(
                text="*Warning*: no sources were cited for this answer, so it may be unreliable 😔"
            )
        ]

    seen_docs_identifiers = set()
    section_blocks: list[Block] = [SectionBlock(text="*Sources:*")]
    included_docs = 0
    for citation_num, d in cited_documents:
        if d.document_id in seen_docs_identifiers:
            continue
        seen_docs_identifiers.add(d.document_id)

        doc_sem_id = d.semantic_identifier
        if d.source_type == DocumentSource.SLACK.value:
            # for legacy reasons, before the switch to how Slack semantic identifiers are constructed
            if "#" not in doc_sem_id:
                doc_sem_id = "#" + doc_sem_id

        # this is needed to try and prevent the line from overflowing
        # if it does overflow, the image gets placed above the title and it
        # looks bad
        doc_sem_id = (
            doc_sem_id[:_MAX_BLURB_LEN] + "..."
            if len(doc_sem_id) > _MAX_BLURB_LEN
            else doc_sem_id
        )

        owner_str = f"By {d.primary_owners[0]}" if d.primary_owners else None
        days_ago_str = _format_doc_updated_at(d.updated_at)
        final_metadata_str = " | ".join(
            ([owner_str] if owner_str else [])
            + ([days_ago_str] if days_ago_str else [])
        )

        document_title = _clean_markdown_link_text(doc_sem_id)
        img_link = source_to_github_img_link(d.source_type)

        section_blocks.append(
            ContextBlock(
                elements=(
                    [
                        ImageElement(
                            image_url=img_link,
                            alt_text=f"{d.source_type.value} logo",
                        )
                    ]
                    if img_link
                    else []
                )
                + [
                    (
                        MarkdownTextObject(text=f"{document_title}")
                        if d.link == ""
                        else MarkdownTextObject(
                            text=f"*<{d.link}|[{citation_num}] {document_title}>*\n{final_metadata_str}"
                        )
                    ),
                ]
            )
        )

        if included_docs >= num_docs_to_display:
            break

    return section_blocks


def _priority_ordered_documents_blocks(
    answer: ChatBasicResponse,
) -> list[Block]:
    top_docs = answer.top_documents if answer.top_documents else None
    if not top_docs:
        return []

    document_blocks = _build_documents_blocks(
        documents=top_docs,
        message_id=answer.message_id,
    )
    if document_blocks:
        document_blocks = [DividerBlock()] + document_blocks
    return document_blocks


def _build_citations_blocks(
    answer: ChatBasicResponse,
) -> list[Block]:
    top_docs = answer.top_documents
    citations = answer.cited_documents or {}
    cited_docs = []
    for citation_num, document_id in citations.items():
        matching_doc = next(
            (d for d in top_docs if d.document_id == document_id),
            None,
        )
        if matching_doc:
            cited_docs.append((citation_num, matching_doc))

    cited_docs.sort()
    citations_block = _build_sources_blocks(cited_documents=cited_docs)
    return citations_block


def _build_answer_blocks(
    answer: ChatBasicResponse, fallback_answer: str
) -> list[SectionBlock]:
    if not answer.answer:
        answer_blocks = [SectionBlock(text=fallback_answer)]
    else:
        # replaces markdown links with slack format links
        formatted_answer = format_slack_message(answer.answer)
        answer_processed = decode_escapes(
            remove_slack_text_interactions(formatted_answer)
        )
        answer_blocks = [
            SectionBlock(text=text) for text in _split_text(answer_processed)
        ]
    return answer_blocks


def _build_qa_response_blocks(
    answer: ChatBasicResponse,
) -> list[Block]:
    top_documents = answer.top_documents
    if not top_documents:
        # This should not happen, even with no docs retrieved, there is still info returned
        raise RuntimeError("Failed to retrieve docs, cannot answer question.")

    if DISABLE_GENERATIVE_AI:
        return []

    filter_block: Block | None = None
    # TODO: add back in
    # if (
    #     retrieval_info.applied_time_cutoff
    #     or retrieval_info.recency_bias_multiplier > 1
    #     or retrieval_info.applied_source_filters
    # ):
    #     filter_text = "Filters: "
    #     if retrieval_info.applied_source_filters:
    #         sources_str = ", ".join(
    #             [s.value for s in retrieval_info.applied_source_filters]
    #         )
    #         filter_text += f"`Sources in [{sources_str}]`"
    #         if (
    #             retrieval_info.applied_time_cutoff
    #             or retrieval_info.recency_bias_multiplier > 1
    #         ):
    #             filter_text += " and "
    #     if retrieval_info.applied_time_cutoff is not None:
    #         time_str = retrieval_info.applied_time_cutoff.strftime("%b %d, %Y")
    #         filter_text += f"`Docs Updated >= {time_str}` "
    #     if retrieval_info.recency_bias_multiplier > 1:
    #         if retrieval_info.applied_time_cutoff is not None:
    #             filter_text += "+ "
    #         filter_text += "`Prioritize Recently Updated Docs`"

    #     filter_block = SectionBlock(text=f"_{filter_text}_")

    answer_blocks = _build_answer_blocks(
        answer=answer,
        fallback_answer="Sorry, I was unable to find an answer, but I did find some potentially relevant docs 🤓",
    )

    response_blocks: list[Block] = []

    if filter_block is not None:
        response_blocks.append(filter_block)

    response_blocks.extend(answer_blocks)

    return response_blocks


def _build_continue_in_web_ui_block(
    message_id: int | None,
) -> Block:
    if message_id is None:
        raise ValueError("No message id provided to build continue in web ui block")
    with get_session_with_current_tenant() as db_session:
        chat_session = get_chat_session_by_message_id(
            db_session=db_session,
            message_id=message_id,
        )
        return ActionsBlock(
            block_id=build_continue_in_web_ui_id(message_id),
            elements=[
                ButtonElement(
                    action_id=CONTINUE_IN_WEB_UI_ACTION_ID,
                    text="Continue Chat in Onyx!",
                    style="primary",
                    url=f"{WEB_DOMAIN}/chat?slackChatId={chat_session.id}",
                ),
            ],
        )


def _build_follow_up_block(message_id: int | None) -> ActionsBlock:
    return ActionsBlock(
        block_id=build_feedback_id(message_id) if message_id is not None else None,
        elements=[
            ButtonElement(
                action_id=IMMEDIATE_RESOLVED_BUTTON_ACTION_ID,
                style="primary",
                text="I'm all set!",
            ),
            ButtonElement(
                action_id=FOLLOWUP_BUTTON_ACTION_ID,
                style="danger",
                text="I need more help from a human!",
            ),
        ],
    )


def build_follow_up_resolved_blocks(
    tag_ids: list[str], group_ids: list[str]
) -> list[Block]:
    tag_str = " ".join([f"<@{tag}>" for tag in tag_ids])
    if tag_str:
        tag_str += " "

    group_str = " ".join([f"<!subteam^{group_id}|>" for group_id in group_ids])
    if group_str:
        group_str += " "

    text = (
        tag_str
        + group_str
        + "Someone has requested more help.\n\n:point_down:Please mark this resolved after answering!"
    )
    text_block = SectionBlock(text=text)
    button_block = ActionsBlock(
        elements=[
            ButtonElement(
                action_id=FOLLOWUP_BUTTON_RESOLVED_ACTION_ID,
                style="primary",
                text="Mark Resolved",
            )
        ]
    )
    return [text_block, button_block]


def build_slack_response_blocks(
    answer: ChatBasicResponse,
    message_info: SlackMessageInfo,
    channel_conf: ChannelConfig | None,
    use_citations: bool,
    feedback_reminder_id: str | None,
    skip_ai_feedback: bool = False,
    offer_ephemeral_publication: bool = False,
    expecting_search_result: bool = False,
    skip_restated_question: bool = False,
) -> list[Block]:
    """
    This function is a top level function that builds all the blocks for the Slack response.
    It also handles combining all the blocks together.
    """
    # If called with the OnyxBot slash command, the question is lost so we have to reshow it
    if not skip_restated_question:
        restate_question_block = get_restate_blocks(
            message_info.thread_messages[-1].message, message_info.is_slash_command
        )
    else:
        restate_question_block = []

    if expecting_search_result:
        answer_blocks = _build_qa_response_blocks(
            answer=answer,
        )

    else:
        answer_blocks = cast(
            list[Block],
            _build_answer_blocks(
                answer=answer,
                fallback_answer="Sorry, I was unable to generate an answer.",
            ),
        )

    web_follow_up_block = []
    if channel_conf and channel_conf.get("show_continue_in_web_ui"):
        web_follow_up_block.append(
            _build_continue_in_web_ui_block(
                message_id=answer.message_id,
            )
        )

    follow_up_block = []
    if (
        channel_conf
        and channel_conf.get("follow_up_tags") is not None
        and not channel_conf.get("is_ephemeral", False)
    ):
        follow_up_block.append(_build_follow_up_block(message_id=answer.message_id))

    publish_ephemeral_message_block = []

    if (
        offer_ephemeral_publication
        and answer.message_id is not None
        and message_info.msg_to_respond is not None
        and channel_conf is not None
    ):
        publish_ephemeral_message_block.append(
            _build_ephemeral_publication_block(
                channel_id=message_info.channel_to_respond,
                chat_message_id=answer.message_id,
                original_question_ts=message_info.msg_to_respond,
                message_info=message_info,
                channel_conf=channel_conf,
                feedback_reminder_id=feedback_reminder_id,
            )
        )

    ai_feedback_block: list[Block] = []

    if answer.message_id is not None and not skip_ai_feedback:
        ai_feedback_block.append(
            _build_qa_feedback_block(
                message_id=answer.message_id,
                feedback_reminder_id=feedback_reminder_id,
            )
        )

    citations_blocks = []
    document_blocks = []
    if use_citations and answer.cited_documents:
        citations_blocks = _build_citations_blocks(answer)
    else:
        document_blocks = _priority_ordered_documents_blocks(answer)

    citations_divider = [DividerBlock()] if citations_blocks else []
    buttons_divider = [DividerBlock()] if web_follow_up_block or follow_up_block else []

    all_blocks = (
        restate_question_block
        + answer_blocks
        + publish_ephemeral_message_block
        + ai_feedback_block
        + citations_divider
        + citations_blocks
        + document_blocks
        + buttons_divider
        + web_follow_up_block
        + follow_up_block
    )

    return all_blocks
