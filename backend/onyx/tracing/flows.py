"""Registry of flow tags applied to LLM-related generation spans.

Each value identifies the *operation* a span represents — e.g.
``contextual_rag_chunk_context`` or ``image_generation``. The provider, model,
and deployment are captured separately on the span's ``model_config``, so the
flow tag should describe **what the call does**, not **who serves it**.

A single source of truth here lets dashboards group/filter without typo drift,
and makes it possible to enforce instrumentation coverage by searching for
``LLMFlow.UNTAGGED_*`` (the sentinel used by the auto-wrap fallback).
"""

from enum import StrEnum


class LLMFlow(StrEnum):
    # Chat / agent
    CHAT_RESPONSE = "chat_response"
    CHAT_HISTORY_SUMMARIZATION = "chat_history_summarization"

    # Secondary LLM flows
    SEMANTIC_QUERY_REPHRASE = "semantic_query_rephrase"
    KEYWORD_QUERY_EXPANSION = "keyword_query_expansion"
    CLASSIFY_SECTION_RELEVANCE = "classify_section_relevance"
    SELECT_SECTIONS_FOR_EXPANSION = "select_sections_for_expansion"
    CHAT_SESSION_NAMING = "chat_session_naming"
    MEMORY_UPDATE = "memory_update"

    # Build session (assistants)
    BUILD_SESSION_NAMING = "build_session_naming"
    BUILD_FOLLOWUP_SUGGESTIONS = "build_followup_suggestions"

    # Federated search helpers
    SLACK_DATE_EXTRACTION = "slack_date_extraction"
    SLACK_QUERY_EXPANSION = "slack_query_expansion"

    # Indexing (docprocessing pod)
    CONTEXTUAL_RAG_DOC_SUMMARY = "contextual_rag_doc_summary"
    CONTEXTUAL_RAG_CHUNK_CONTEXT = "contextual_rag_chunk_context"
    IMAGE_SUMMARIZATION = "image_summarization"

    # Knowledge graph
    KG_DOCUMENT_CLASSIFICATION = "kg_document_classification"
    KG_DEEP_EXTRACTION = "kg_deep_extraction"

    # Image generation
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDIT = "image_edit"

    # Voice
    STT = "stt"
    TTS = "tts"

    # Embeddings / rerank / intent (cross-process to model_server)
    EMBED_QUERY = "embed_query"
    EMBED_PASSAGE = "embed_passage"
    RERANK = "rerank"
    INTENT_CLASSIFICATION = "intent_classification"

    # Sentinels — emitted by the LLM auto-wrap fallback when a caller did not
    # tag the call. Showing up in dashboards is a signal to add an explicit
    # ``llm_generation_span`` at the call site with the right tag.
    UNTAGGED_INVOKE = "untagged_invoke"
    UNTAGGED_STREAM = "untagged_stream"
