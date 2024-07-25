import re
from datetime import datetime
from re import Match

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

from danswer.chat.models import DanswerQuote
from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import SearchFeedbackType
from danswer.configs.danswerbot_configs import DANSWER_BOT_NUM_DOCS_TO_DISPLAY
from danswer.danswerbot.slack.constants import DISLIKE_BLOCK_ACTION_ID
from danswer.danswerbot.slack.constants import FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID
from danswer.danswerbot.slack.constants import FOLLOWUP_BUTTON_ACTION_ID
from danswer.danswerbot.slack.constants import FOLLOWUP_BUTTON_RESOLVED_ACTION_ID
from danswer.danswerbot.slack.constants import GENERATE_ANSWER_BUTTON_ACTION_ID
from danswer.danswerbot.slack.constants import IMMEDIATE_RESOLVED_BUTTON_ACTION_ID
from danswer.danswerbot.slack.constants import LIKE_BLOCK_ACTION_ID
from danswer.danswerbot.slack.icons import source_to_github_img_link
from danswer.danswerbot.slack.utils import build_feedback_id
from danswer.danswerbot.slack.utils import remove_slack_text_interactions
from danswer.danswerbot.slack.utils import translate_vespa_highlight_to_slack
from danswer.search.models import SavedSearchDoc
from danswer.utils.text_processing import decode_escapes
from danswer.utils.text_processing import replace_whitespaces_w_space

_MAX_BLURB_LEN = 45


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


def _process_citations_for_slack(text: str) -> str:
    """
    Converts instances of [[x]](LINK) in the input text to Slack's link format <LINK|[x]>.

    Args:
    - text (str): The input string containing markdown links.

    Returns:
    - str: The string with markdown links converted to Slack format.
    """
    # Regular expression to find all instances of [[x]](LINK)
    pattern = r"\[\[(.*?)\]\]\((.*?)\)"

    # Function to replace each found instance with Slack's format
    def slack_link_format(match: Match) -> str:
        link_text = match.group(1)
        link_url = match.group(2)
        return f"<{link_url}|[{link_text}]>"

    # Substitute all matches in the input text
    return re.sub(pattern, slack_link_format, text)


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


def clean_markdown_link_text(text: str) -> str:
    # Remove any newlines within the text
    return text.replace("\n", " ").strip()


def build_qa_feedback_block(
    message_id: int, feedback_reminder_id: str | None = None
) -> Block:
    return ActionsBlock(
        block_id=build_feedback_id(message_id),
        elements=[
            ButtonElement(
                action_id=LIKE_BLOCK_ACTION_ID,
                text="👍 Helpful",
                style="primary",
                value=feedback_reminder_id,
            ),
            ButtonElement(
                action_id=DISLIKE_BLOCK_ACTION_ID,
                text="👎 Not helpful",
                value=feedback_reminder_id,
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


def build_doc_feedback_block(
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
    is_bot_msg: bool,
) -> list[Block]:
    # Only the slash command needs this context because the user doesn't see their own input
    if not is_bot_msg:
        return []

    return [
        HeaderBlock(text="Responding to the Query"),
        SectionBlock(text=f"```{msg}```"),
    ]


def build_documents_blocks(
    documents: list[SavedSearchDoc],
    message_id: int | None,
    num_docs_to_display: int = DANSWER_BOT_NUM_DOCS_TO_DISPLAY,
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

        doc_sem_id = d.semantic_identifier
        if d.source_type == DocumentSource.SLACK.value:
            doc_sem_id = "#" + doc_sem_id

        used_chars = len(doc_sem_id) + 3
        match_str = translate_vespa_highlight_to_slack(d.match_highlights, used_chars)

        included_docs += 1

        header_line = f"{doc_sem_id}\n"
        if d.link:
            header_line = f"<{d.link}|{doc_sem_id}>\n"

        updated_at_line = ""
        if d.updated_at is not None:
            updated_at_line = (
                f"_Updated {timeago.format(d.updated_at, datetime.now(pytz.utc))}_\n"
            )

        body_text = f">{remove_slack_text_interactions(match_str)}"

        block_text = header_line + updated_at_line + body_text

        feedback: ButtonElement | dict = {}
        if message_id is not None:
            feedback = build_doc_feedback_block(
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


def build_sources_blocks(
    cited_documents: list[tuple[int, SavedSearchDoc]],
    num_docs_to_display: int = DANSWER_BOT_NUM_DOCS_TO_DISPLAY,
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
        days_ago_str = (
            timeago.format(d.updated_at, datetime.now(pytz.utc))
            if d.updated_at
            else None
        )
        final_metadata_str = " | ".join(
            ([owner_str] if owner_str else [])
            + ([days_ago_str] if days_ago_str else [])
        )

        document_title = clean_markdown_link_text(doc_sem_id)
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
                    MarkdownTextObject(
                        text=f"*<{d.link}|[{citation_num}] {document_title}>*\n{final_metadata_str}"
                    ),
                ]
            )
        )

        if included_docs >= num_docs_to_display:
            break

    return section_blocks


def build_quotes_block(
    quotes: list[DanswerQuote],
) -> list[Block]:
    quote_lines: list[str] = []
    doc_to_quotes: dict[str, list[str]] = {}
    doc_to_link: dict[str, str] = {}
    doc_to_sem_id: dict[str, str] = {}
    for q in quotes:
        quote = q.quote
        doc_id = q.document_id
        doc_link = q.link
        doc_name = q.semantic_identifier
        if doc_link and doc_name and doc_id and quote:
            if doc_id not in doc_to_quotes:
                doc_to_quotes[doc_id] = [quote]
                doc_to_link[doc_id] = doc_link
                doc_to_sem_id[doc_id] = (
                    doc_name
                    if q.source_type != DocumentSource.SLACK.value
                    else "#" + doc_name
                )
            else:
                doc_to_quotes[doc_id].append(quote)

    for doc_id, quote_strs in doc_to_quotes.items():
        quotes_str_clean = [
            replace_whitespaces_w_space(q_str).strip() for q_str in quote_strs
        ]
        longest_quotes = sorted(quotes_str_clean, key=len, reverse=True)[:5]
        single_quote_str = "\n".join([f"```{q_str}```" for q_str in longest_quotes])
        link = doc_to_link[doc_id]
        sem_id = doc_to_sem_id[doc_id]
        quote_lines.append(
            f"<{link}|{sem_id}>:\n{remove_slack_text_interactions(single_quote_str)}"
        )

    if not doc_to_quotes:
        return []

    return [SectionBlock(text="*Relevant Snippets*\n" + "\n".join(quote_lines))]


def build_standard_answer_blocks(
    answer_message: str,
) -> list[Block]:
    generate_button_block = ButtonElement(
        action_id=GENERATE_ANSWER_BUTTON_ACTION_ID,
        text="Generate Full Answer",
    )
    answer_block = SectionBlock(text=answer_message)
    return [
        answer_block,
        ActionsBlock(
            elements=[generate_button_block],
        ),
    ]


def build_qa_response_blocks(
    message_id: int | None,
    answer: str | None,
    quotes: list[DanswerQuote] | None,
    source_filters: list[DocumentSource] | None,
    time_cutoff: datetime | None,
    favor_recent: bool,
    skip_quotes: bool = False,
    process_message_for_citations: bool = False,
    skip_ai_feedback: bool = False,
    feedback_reminder_id: str | None = None,
) -> list[Block]:
    if DISABLE_GENERATIVE_AI:
        return []

    quotes_blocks: list[Block] = []

    filter_block: Block | None = None
    if time_cutoff or favor_recent or source_filters:
        filter_text = "Filters: "
        if source_filters:
            sources_str = ", ".join([s.value for s in source_filters])
            filter_text += f"`Sources in [{sources_str}]`"
            if time_cutoff or favor_recent:
                filter_text += " and "
        if time_cutoff is not None:
            time_str = time_cutoff.strftime("%b %d, %Y")
            filter_text += f"`Docs Updated >= {time_str}` "
        if favor_recent:
            if time_cutoff is not None:
                filter_text += "+ "
            filter_text += "`Prioritize Recently Updated Docs`"

        filter_block = SectionBlock(text=f"_{filter_text}_")

    if not answer:
        answer_blocks = [
            SectionBlock(
                text="Sorry, I was unable to find an answer, but I did find some potentially relevant docs 🤓"
            )
        ]
    else:
        answer_processed = decode_escapes(remove_slack_text_interactions(answer))
        if process_message_for_citations:
            answer_processed = _process_citations_for_slack(answer_processed)
        answer_blocks = [
            SectionBlock(text=text) for text in _split_text(answer_processed)
        ]
        if quotes:
            quotes_blocks = build_quotes_block(quotes)

        # if no quotes OR `build_quotes_block()` did not give back any blocks
        if not quotes_blocks:
            quotes_blocks = [
                SectionBlock(
                    text="*Warning*: no sources were quoted for this answer, so it may be unreliable 😔"
                )
            ]

    response_blocks: list[Block] = []

    if filter_block is not None:
        response_blocks.append(filter_block)

    response_blocks.extend(answer_blocks)

    if message_id is not None and not skip_ai_feedback:
        response_blocks.append(
            build_qa_feedback_block(
                message_id=message_id, feedback_reminder_id=feedback_reminder_id
            )
        )

    if not skip_quotes:
        response_blocks.extend(quotes_blocks)

    return response_blocks


def build_follow_up_block(message_id: int | None) -> ActionsBlock:
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
