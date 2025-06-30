import re
from datetime import datetime
from datetime import timedelta
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.app_configs import NUM_SLACK_CHUNKS
from onyx.configs.app_configs import NUM_SLACK_SEARCH_DOCS
from onyx.configs.app_configs import SLACK_USER_TOKEN
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import TextSection
from onyx.context.search.federated.models import SLACK_ELEMENT_TYPE_MAP
from onyx.context.search.federated.models import SlackElement
from onyx.context.search.federated.models import SlackMessage
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.document import DocumentSource
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import (
    get_multipass_config,
)
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


def build_slack_query(query: SearchQuery) -> str:
    raw_query = " ".join(query.processed_keywords)

    # in the future, we could ask an LLM to generate in/from filters and fuzzy match them
    # to actual user/channel names (slack will take care of the access control)
    filter_query = ""
    time_cutoff = query.filters.time_cutoff
    if time_cutoff is not None:
        # slack after: is exclusive, so we need to subtract one day
        time_cutoff = time_cutoff - timedelta(days=1)
        filter_query = f"after:{time_cutoff.strftime('%Y-%m-%d')}"

    return " ".join([raw_query, filter_query])


def get_user_id_mapping(text: str) -> dict[str, str]:
    """
    Gets the user id mapping from the slack message text.
    E.g., <@U0123ABC|John Doe> hello there... -> {"U0123ABC": "John Doe"}
    """
    user_id_mapping: dict[str, str] = {}
    for match in re.finditer(r"<@([A-Z0-9]+)\|([^>]+)>", text):
        user_id_mapping[match.group(1)] = match.group(2)
    return user_id_mapping


def get_unnested_elements(
    elements: list[dict[str, Any]], user_id_mapping: dict[str, str]
) -> list[SlackElement]:
    """
    Unnests a tree of nodes into a list of leaf SlackElements.
    Only elements that are in SLACK_ELEMENT_TYPE_MAP are extracted.
    """
    flattened: list[SlackElement] = []

    for element in elements:
        if "elements" in element:
            flattened.extend(
                get_unnested_elements(element["elements"], user_id_mapping)
            )
            continue

        element_type: str | None = element.get("type")
        if element_type not in SLACK_ELEMENT_TYPE_MAP:
            continue

        text: str = ""
        for field in SLACK_ELEMENT_TYPE_MAP[element_type]:
            text = element.get(field, "")
            if text:
                break
        highlighted: bool = element.get("style", {}).get("client_highlight", False)
        if element_type == "user":
            text = user_id_mapping.get(text, "")
        if text:
            flattened.append(SlackElement(text=text, highlight=highlighted))

    return flattened


def get_relevant_regions(
    elements: list[SlackElement], window: int
) -> tuple[list[str], set[str]]:
    """
    Takes in a list of elements: {"text": str, "style"?: dict[str, str]}
    and returns a tuple of (relevant regions, highlighted strings)
    E.g.,
    elements = [
        SlackElement(text="Hello "),
        SlackElement(text="world", highlight=True),
        SlackElement(text=". How are "),
        SlackElement(text="you", highlight=True),
        SlackElement(text="? "),
        SlackElement(text="I'm"),
        SlackElement(text="fine "),
        SlackElement(text="thanks!", highlight=True),
    ]
    window = 1
    Returns: ["Hello world. How are you?", "fine thanks!"], {"world", "you", "thanks!"}
    """
    texts = [element.text for element in elements]

    highlighted_texts: set[str] = set()
    highlighted_idxs: list[int] = []
    for i, element in enumerate(elements):
        if element.highlight:
            highlighted_texts.add(element.text)
            highlighted_idxs.append(i)

    # grab text within window of highlighted text
    relevant_regions: list[str] = []
    last_end = -1
    for idx in highlighted_idxs:
        start = max(0, idx - window)
        end = idx + window + 1

        if start < last_end:
            start = last_end
            relevant_regions[-1] += "".join(texts[start:end])
        else:
            relevant_regions.append("".join(texts[start:end]))
        last_end = end

    return relevant_regions, highlighted_texts


def process_slack_message(
    match: dict[str, Any], query: SearchQuery
) -> SlackMessage | None:
    text: str | None = match.get("text")
    permalink: str | None = match.get("permalink")
    thread_ts: str | None = match.get("ts")
    channel_id: str | None = match.get("channel", {}).get("id")
    channel_name: str | None = match.get("channel", {}).get("name")
    username: str | None = match.get("username")
    if (  # can't use any() because of type checking :(
        text is None
        or permalink is None
        or thread_ts is None
        or channel_id is None
        or channel_name is None
        or username is None
    ):
        return None

    # generate metadata and document id
    document_id = f"{channel_id}_{thread_ts.replace('.', '')}"
    metadata: dict[str, str | list[str]] = {
        k: str(v)
        for k, v in {"channel": channel_name, "sender": username}.items()
        if v is not None
    }

    # generate user id mapping
    user_id_mapping = get_user_id_mapping(text)

    # compute recency bias (parallels vespa calculation)
    decay_factor = DOC_TIME_DECAY * query.recency_bias_multiplier
    doc_time = datetime.fromtimestamp(float(thread_ts))
    doc_age_years = (datetime.now() - doc_time).total_seconds() / (365 * 24 * 60 * 60)
    recency_bias = max(1 / (1 + decay_factor * doc_age_years), 0.75)

    # compute score
    score: float = match.get("score", 0.0)  # 0 - inf?
    score = 0.0  # for now
    # TODO: maybe map to our scores using a polynomial?

    # get elements and relevant regions
    elements = get_unnested_elements(match.get("blocks", []), user_id_mapping)
    relevant_regions, highlighted_texts = get_relevant_regions(elements, window=2)
    if not relevant_regions:
        return None

    # get semantic identifier
    first_message = relevant_regions[0]
    snippet = (
        first_message[:50].rstrip() + "..."
        if len(first_message) > 50
        else first_message
    ).replace("\n", " ")
    doc_sem_id = f"{username} in #{channel_name}: {snippet}"

    return SlackMessage(
        document_id=document_id,
        texts=relevant_regions,
        highlighted_texts=highlighted_texts,
        link=permalink,
        semantic_identifier=doc_sem_id,
        metadata=metadata,
        timestamp=doc_time,
        score=score,
        recency_bias=recency_bias,
    )


@log_function_time(print_only=True)
def slack_retrieval(query: SearchQuery, db_session: Session) -> list[InferenceChunk]:
    # token isn't validated yet
    slack_client = WebClient(token=SLACK_USER_TOKEN)

    # query slack
    slack_query = build_slack_query(query)
    try:
        response = slack_client.search_messages(
            query=slack_query, count=NUM_SLACK_SEARCH_DOCS, highlight=True
        )
        response.validate()
        messages: dict[str, Any] = response.get("messages", {})
        matches: list[dict[str, Any]] = messages.get("matches", [])
    except SlackApiError as e:
        logger.error(f"Slack API error: {e}")
        return []

    # convert response to slack messages
    slack_messages = [
        message
        for match in matches
        if (message := process_slack_message(match, query)) is not None
    ]
    if not slack_messages:
        return []
    doc_slack_messages = {
        slack_message.document_id: slack_message for slack_message in slack_messages
    }

    # convert slack messages to index documents
    index_docs = [
        IndexingDocument(
            id=slack_message.document_id,
            sections=[
                TextSection(
                    text="\n".join(slack_message.texts), link=slack_message.link
                )
            ],
            processed_sections=[
                TextSection(
                    text="\n".join(slack_message.texts), link=slack_message.link
                )
            ],
            source=DocumentSource.SLACK,
            semantic_identifier=slack_message.semantic_identifier,
            metadata=slack_message.metadata,
            doc_updated_at=slack_message.timestamp,
        )
        for slack_message in slack_messages
    ]

    # convert index docs to doc aware chunks
    search_settings = get_current_search_settings(db_session)
    embedder = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings
    )
    multipass_config = get_multipass_config(search_settings)
    enable_contextual_rag = (
        search_settings.enable_contextual_rag or ENABLE_CONTEXTUAL_RAG
    )
    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        # do we need all these?
        enable_multipass=multipass_config.multipass_indexing,
        enable_large_chunks=multipass_config.enable_large_chunks,
        enable_contextual_rag=enable_contextual_rag,
    )
    chunks = chunker.chunk(index_docs)

    # convert chunks to inference chunks
    top_chunks: list[InferenceChunk] = []
    for chunk in chunks:
        document_id = chunk.source_document.id

        # create highlighted text
        match_highlights = chunk.content
        for highlight in sorted(
            doc_slack_messages[document_id].highlighted_texts, key=len
        ):
            match_highlights = match_highlights.replace(
                highlight, f"<hi>{highlight}</hi>"
            )

        top_chunks.append(
            InferenceChunk(
                chunk_id=chunk.chunk_id,
                blurb=chunk.blurb,
                content=chunk.content,
                source_links=chunk.source_links,
                image_file_id=chunk.image_file_id,
                section_continuation=chunk.section_continuation,
                semantic_identifier=doc_slack_messages[document_id].semantic_identifier,
                document_id=document_id,
                source_type=DocumentSource.SLACK,
                title=chunk.title_prefix,
                boost=0,
                recency_bias=doc_slack_messages[document_id].recency_bias,
                score=doc_slack_messages[document_id].score,
                hidden=False,
                is_relevant=True,
                relevance_explanation="",
                metadata=doc_slack_messages[document_id].metadata,
                match_highlights=[match_highlights],
                doc_summary="",
                chunk_context="",
                updated_at=doc_slack_messages[document_id].timestamp,
            )
        )
        if len(top_chunks) >= NUM_SLACK_CHUNKS:
            break

    return top_chunks
