import re
from datetime import datetime
from datetime import timedelta
from typing import Any

from langchain_core.messages import HumanMessage
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.app_configs import NUM_SLACK_SEARCH_DOCS
from onyx.configs.app_configs import SLACK_USER_TOKEN
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import TextSection
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
from onyx.indexing.models import DocAwareChunk
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.llm.utils import message_to_string
from onyx.prompts.federated_search import SLACK_QUERY_EXPANSION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

HIGHLIGHT_START_CHAR = "\ue000"
HIGHLIGHT_END_CHAR = "\ue001"


def build_slack_queries(query: SearchQuery, llm: LLM) -> list[str]:
    # get time filter
    time_filter = ""
    time_cutoff = query.filters.time_cutoff
    if time_cutoff is not None:
        # slack after: is exclusive, so we need to subtract one day
        time_cutoff = time_cutoff - timedelta(days=1)
        time_filter = f" after:{time_cutoff.strftime('%Y-%m-%d')}"

    # use llm to generate slack queries
    prompt = SLACK_QUERY_EXPANSION_PROMPT.format(query=query.query)
    try:
        msg = HumanMessage(content=prompt)
        response = llm.invoke([msg])
        rephrased_queries = message_to_string(response).split("\n")
    except Exception as e:
        logger.error(f"Error expanding query: {e}")
        rephrased_queries = [query.query]

    return [
        rephrased_query.strip() + time_filter for rephrased_query in rephrased_queries
    ]


def query_slack(query_string: str, original_query: SearchQuery) -> list[SlackMessage]:
    # query slack
    slack_client = WebClient(token=SLACK_USER_TOKEN)
    try:
        response = slack_client.search_messages(
            query=query_string, count=NUM_SLACK_SEARCH_DOCS, highlight=True
        )
        response.validate()
        messages: dict[str, Any] = response.get("messages", {})
        matches: list[dict[str, Any]] = messages.get("matches", [])
    except SlackApiError as e:
        logger.error(f"Slack API error: {e}")
        return []

    # convert matches to slack messages
    slack_messages: list[SlackMessage] = []
    for match in matches:
        text: str | None = match.get("text")
        permalink: str | None = match.get("permalink")
        thread_ts: str | None = match.get("ts")
        channel_id: str | None = match.get("channel", {}).get("id")
        channel_name: str | None = match.get("channel", {}).get("name")
        username: str | None = match.get("username")
        score: float = match.get("score", 0.0)
        if (  # can't use any() because of type checking :(
            not text
            or not permalink
            or not thread_ts
            or not channel_id
            or not channel_name
            or not username
        ):
            continue

        # generate metadata and document id
        document_id = f"{channel_id}_{thread_ts.replace('.', '')}"
        metadata: dict[str, str | list[str]] = {
            "channel": channel_name,
            "sender": username,
        }

        # compute recency bias (parallels vespa calculation)
        decay_factor = DOC_TIME_DECAY * original_query.recency_bias_multiplier
        doc_time = datetime.fromtimestamp(float(thread_ts))
        doc_age_years = (datetime.now() - doc_time).total_seconds() / (
            365 * 24 * 60 * 60
        )
        recency_bias = max(1 / (1 + decay_factor * doc_age_years), 0.75)

        # extract out the highlighted texts
        highlighted_texts = set(
            re.findall(
                rf"{re.escape(HIGHLIGHT_START_CHAR)}(.*?){re.escape(HIGHLIGHT_END_CHAR)}",
                text,
            )
        )
        cleaned_text = text.replace(HIGHLIGHT_START_CHAR, "").replace(
            HIGHLIGHT_END_CHAR, ""
        )

        # get the semantic identifier
        snippet = (text[:50].rstrip() + "..." if len(text) > 50 else text).replace(
            "\n", " "
        )
        doc_sem_id = f"{username} in #{channel_name}: {snippet}"

        slack_messages.append(
            SlackMessage(
                document_id=document_id,
                link=permalink,
                metadata=metadata,
                timestamp=doc_time,
                recency_bias=recency_bias,
                semantic_identifier=doc_sem_id,
                text=cleaned_text,
                highlighted_texts=highlighted_texts,
                slack_score=score,
            )
        )

    return slack_messages


def merge_slack_messages(
    slack_messages: list[list[SlackMessage]],
) -> tuple[list[SlackMessage], dict[str, SlackMessage]]:
    merged_messages: list[SlackMessage] = []
    docid_to_message: dict[str, SlackMessage] = {}

    for messages in slack_messages:
        for message in messages:
            if message.document_id in docid_to_message:
                # update the score and highlighted texts, rest should be identical
                docid_to_message[message.document_id].slack_score = max(
                    docid_to_message[message.document_id].slack_score,
                    message.slack_score,
                )
                docid_to_message[message.document_id].highlighted_texts.update(
                    message.highlighted_texts
                )
                continue

            # add the message to the list
            docid_to_message[message.document_id] = message
            merged_messages.append(message)

    # re-sort by score
    merged_messages.sort(key=lambda x: x.slack_score, reverse=True)

    return merged_messages, docid_to_message


@log_function_time(print_only=True)
def slack_retrieval(query: SearchQuery, db_session: Session) -> list[InferenceChunk]:
    # query slack
    llm, fast_llm = get_default_llms()
    query_strings = build_slack_queries(query, fast_llm)

    results: list[list[SlackMessage]] = run_functions_tuples_in_parallel(
        [(query_slack, (query_string, query)) for query_string in query_strings]
    )
    slack_messages, docid_to_message = merge_slack_messages(results)
    if not slack_messages:
        return []

    # get the highlighted texts from shortest to longest
    highlighted_texts: set[str] = set()
    for slack_message in slack_messages:
        highlighted_texts.update(slack_message.highlighted_texts)
    sorted_highlighted_texts = sorted(highlighted_texts, key=len)

    # convert slack messages to index documents
    index_docs: list[IndexingDocument] = []
    for slack_message in slack_messages:
        section: TextSection = TextSection(
            text=slack_message.text, link=slack_message.link
        )
        index_docs.append(
            IndexingDocument(
                id=slack_message.document_id,
                sections=[section],
                processed_sections=[section],
                source=DocumentSource.SLACK,
                title=slack_message.semantic_identifier,
                semantic_identifier=slack_message.semantic_identifier,
                metadata=slack_message.metadata,
                doc_updated_at=slack_message.timestamp,
            )
        )

    # chunk index docs into doc aware chunks
    # a single index doc can get split into multiple chunks
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

    # prune chunks without any highlighted texts
    relevant_chunks: list[DocAwareChunk] = []
    chunkid_to_match_highlight: dict[str, str] = {}
    for chunk in chunks:
        match_highlight = chunk.content
        # this is faster than a regex, especially with more highlights
        for highlight in sorted_highlighted_texts:
            match_highlight = match_highlight.replace(
                highlight, f"<hi>{highlight}</hi>"
            )

        # if nothing got replaced, the chunk is irrelevant
        if len(match_highlight) == len(chunk.content):
            continue

        chunk_id = f"{chunk.source_document.id}__{chunk.chunk_id}"
        relevant_chunks.append(chunk)
        chunkid_to_match_highlight[chunk_id] = match_highlight

    # convert to inference chunks
    top_chunks: list[InferenceChunk] = []
    for chunk in relevant_chunks:
        document_id = chunk.source_document.id
        chunk_id = f"{document_id}__{chunk.chunk_id}"

        top_chunks.append(
            InferenceChunk(
                chunk_id=chunk.chunk_id,
                blurb=chunk.blurb,
                content=chunk.content,
                source_links=chunk.source_links,
                image_file_id=chunk.image_file_id,
                section_continuation=chunk.section_continuation,
                semantic_identifier=docid_to_message[document_id].semantic_identifier,
                document_id=document_id,
                source_type=DocumentSource.SLACK,
                title=chunk.title_prefix,
                boost=0,
                recency_bias=docid_to_message[document_id].recency_bias,
                score=0.0,  # not using slack score as it's a different scale
                hidden=False,
                is_relevant=True,
                relevance_explanation="",
                metadata=docid_to_message[document_id].metadata,
                match_highlights=[chunkid_to_match_highlight[chunk_id]],
                doc_summary="",
                chunk_context="",
                updated_at=docid_to_message[document_id].timestamp,
            )
        )
    return top_chunks
