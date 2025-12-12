"""
Avatar query service for executing searches against avatars.

This module handles the core logic for querying avatars, including:
- Owned documents mode (instant, no permission required)
- Accessible documents mode (requires permission if answer found)
- Permission request creation and caching
"""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import QueryExpansionType
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import get_query_embedding
from onyx.db.avatar import check_rate_limit
from onyx.db.avatar import create_permission_request
from onyx.db.avatar import get_avatar_by_id
from onyx.db.avatar import log_avatar_query
from onyx.db.avatar import should_auto_approve
from onyx.db.enums import AvatarPermissionRequestStatus
from onyx.db.enums import AvatarQueryMode
from onyx.db.models import Avatar
from onyx.db.models import User
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.llm.factory import get_default_llms
from onyx.llm.factory import get_main_llm_from_tuple
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.server.features.avatar.models import AvatarQueryResponse
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


# Prompt for generating answers from avatar query results
AVATAR_ANSWER_SYSTEM_PROMPT = """You are a helpful assistant answering questions based on documents \
owned by or accessible to a specific user (the "avatar").

Your task is to synthesize information from the provided document excerpts and \
generate a clear, accurate answer to the user's question.

Guidelines:
- Base your answer ONLY on the provided document excerpts
- Be concise but thorough
- If the documents don't contain enough information to fully answer the question, \
acknowledge what information is available and what is missing
- Use a professional, helpful tone
- When referencing specific information, indicate which document it came from using [1], [2], etc."""

AVATAR_ANSWER_USER_PROMPT_TEMPLATE = """Based on the following document excerpts from {avatar_name}'s \
documents, please answer this question:

Question: {query}

Document Excerpts:
{context}

Please provide a clear, helpful answer based on the information above."""


# Minimum score threshold for considering results "good enough"
MIN_RESULT_SCORE = 0.3
# Minimum number of chunks needed to consider a query successful
MIN_CHUNKS_FOR_ANSWER = 1


def _build_owned_documents_filters(
    avatar: Avatar,
    user: User,
    db_session: Session,
) -> IndexFilters:
    """Build filters for querying documents owned by the avatar's user."""
    return IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        # should still only give back docs the query user has access to
        access_control_list=list(build_access_filters_for_user(user, db_session)),
        primary_owner_emails=[avatar.user.email],
        tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
    )


def _build_accessible_documents_filters(
    avatar: Avatar,
    db_session: Session,
) -> IndexFilters:
    """Build filters for querying all documents accessible to the avatar's user."""
    # Get the ACL for the avatar's user (not the requester)
    user_acl = build_access_filters_for_user(avatar.user, db_session)
    return IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        access_control_list=list(user_acl),
        tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
    )


def _execute_search(
    query: str,
    filters: IndexFilters,
    db_session: Session,
    num_results: int = 10,
) -> list[InferenceChunk]:
    """Execute a hybrid search with the given filters.

    Uses the document index's hybrid_retrieval which combines
    semantic (embedding) and keyword search.
    """
    try:
        # Get query embedding
        query_embedding = get_query_embedding(query, db_session)

        # Get document index
        document_index = get_current_primary_default_document_index(db_session)

        # Execute hybrid search
        chunks = document_index.hybrid_retrieval(
            query=query,
            query_embedding=query_embedding,
            final_keywords=None,
            filters=filters,
            hybrid_alpha=0.5,  # Balance between semantic and keyword
            time_decay_multiplier=1.0,
            num_to_retrieve=num_results,
            ranking_profile_type=QueryExpansionType.SEMANTIC,
        )

        return chunks[:num_results]
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


def _generate_answer(
    query: str,
    chunks: list[InferenceChunk],
    avatar: Avatar,
) -> str | None:
    """Generate an answer from the retrieved chunks using the LLM.

    Uses the default LLM to generate a contextual answer based on the
    retrieved document chunks, similar to the normal chat flow.
    """
    if not chunks:
        return None

    # Build context from chunks
    context_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        source = chunk.semantic_identifier or chunk.document_id
        context_parts.append(f"[{i}] Source: {source}\n{chunk.content}")

    context = "\n\n---\n\n".join(context_parts)

    # Get avatar display name
    avatar_name = avatar.name or avatar.user.email

    # Build the user prompt
    user_prompt = AVATAR_ANSWER_USER_PROMPT_TEMPLATE.format(
        avatar_name=avatar_name,
        query=query,
        context=context,
    )

    try:
        # Get the default LLM (use the fast model for avatar queries)
        llms = get_default_llms()
        llm = get_main_llm_from_tuple(llms)

        # Generate the answer with properly typed messages
        system_msg: SystemMessage = {
            "role": "system",
            "content": AVATAR_ANSWER_SYSTEM_PROMPT,
        }
        user_msg: UserMessageWithText = {
            "role": "user",
            "content": user_prompt,
        }

        response = llm.invoke([system_msg, user_msg])

        # Access the content from the ModelResponse structure
        if response and response.choice and response.choice.message:
            content = response.choice.message.content
            if content:
                return content

        return None

    except Exception as e:
        logger.error(f"Failed to generate LLM answer for avatar query: {e}")
        # Fall back to simple summary if LLM fails
        summary_parts = []
        for i, chunk in enumerate(chunks[:5], 1):
            source = chunk.semantic_identifier or chunk.document_id
            preview = (
                chunk.content[:200] + "..."
                if len(chunk.content) > 200
                else chunk.content
            )
            summary_parts.append(f"[{i}] {source}: {preview}")

        return "\n\n".join(summary_parts)


def _has_good_results(chunks: list[InferenceChunk]) -> bool:
    """Check if the search results are good enough to proceed."""
    if len(chunks) < MIN_CHUNKS_FOR_ANSWER:
        return False

    # Check if at least one chunk has a good score
    for chunk in chunks:
        if chunk.score and chunk.score >= MIN_RESULT_SCORE:
            return True

    return len(chunks) >= MIN_CHUNKS_FOR_ANSWER


def execute_avatar_query(
    avatar_id: int,
    query: str,
    query_mode: AvatarQueryMode,
    requester: User,
    db_session: Session,
    chat_session_id: UUID | None = None,
    chat_message_id: int | None = None,
) -> AvatarQueryResponse:
    """Execute a query against an avatar.

    Args:
        avatar_id: ID of the avatar to query
        query: The search query text
        query_mode: Whether to search owned documents or all accessible documents
        requester: The user making the request
        db_session: Database session
        chat_session_id: Optional chat session ID for context
        chat_message_id: Optional chat message ID for context

    Returns:
        AvatarQueryResponse with status and results
    """
    # Get the avatar
    avatar = get_avatar_by_id(avatar_id, db_session)
    if not avatar:
        return AvatarQueryResponse(
            status="error",
            message="Avatar not found",
        )

    # Check if avatar is enabled
    if not avatar.is_enabled:
        return AvatarQueryResponse(
            status="disabled",
            message="This avatar is currently disabled",
        )

    # Check if the requested mode is allowed
    if (
        query_mode == AvatarQueryMode.ACCESSIBLE_DOCUMENTS
        and not avatar.allow_accessible_mode
    ):
        return AvatarQueryResponse(
            status="error",
            message="This avatar does not allow accessible documents mode",
        )

    # Check rate limit
    if not check_rate_limit(avatar_id, requester.id, db_session):
        return AvatarQueryResponse(
            status="rate_limited",
            message="You have exceeded the rate limit for this avatar",
        )

    # Log the query
    log_avatar_query(
        avatar_id=avatar_id,
        requester_id=requester.id,
        query_mode=query_mode,
        query_text=query,
        db_session=db_session,
    )

    if query_mode == AvatarQueryMode.OWNED_DOCUMENTS:
        # Direct search on owned documents - no permission needed
        filters = _build_owned_documents_filters(avatar, requester, db_session)
        chunks = _execute_search(query, filters, db_session)

        if not _has_good_results(chunks):
            return AvatarQueryResponse(
                status="no_results",
                message="No relevant documents found",
            )

        # Generate answer from chunks using LLM
        answer = _generate_answer(query, chunks, avatar)

        return AvatarQueryResponse(
            status="success",
            answer=answer,
            source_document_ids=[chunk.document_id for chunk in chunks],
        )

    elif query_mode == AvatarQueryMode.ACCESSIBLE_DOCUMENTS:
        # Check auto-approve rules first
        if should_auto_approve(avatar, requester):
            # Execute search and return results directly
            filters = _build_accessible_documents_filters(avatar, db_session)
            chunks = _execute_search(query, filters, db_session)

            if not _has_good_results(chunks):
                return AvatarQueryResponse(
                    status="no_results",
                    message="No relevant documents found",
                )

            answer = _generate_answer(query, chunks, avatar)

            return AvatarQueryResponse(
                status="success",
                answer=answer,
                source_document_ids=[chunk.document_id for chunk in chunks],
            )

        # For non-auto-approved requests, run the query in the background
        # Create permission request in PROCESSING status
        permission_request = create_permission_request(
            avatar_id=avatar_id,
            requester_id=requester.id,
            query_text=query if avatar.show_query_in_request else None,
            db_session=db_session,
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            status=AvatarPermissionRequestStatus.PROCESSING,
        )

        # Commit to get the request ID before queuing the task
        db_session.commit()

        # Queue the background task via Celery client app
        from onyx.background.celery.versioned_apps.client import app as client_app
        from onyx.configs.constants import OnyxCeleryTask

        task = client_app.send_task(
            OnyxCeleryTask.AVATAR_QUERY_TASK,
            kwargs={
                "permission_request_id": permission_request.id,
                "tenant_id": get_current_tenant_id() if MULTI_TENANT else None,
            },
        )

        # Update with task ID
        permission_request.task_id = task.id
        db_session.commit()

        logger.info(
            f"Queued avatar query task {task.id} for permission request {permission_request.id}"
        )

        return AvatarQueryResponse(
            status="processing",
            permission_request_id=permission_request.id,
            message=(
                "Your query is being processed. You will be notified if an answer "
                f"is found AND {avatar.user.email} approves the request.."
            ),
        )

    return AvatarQueryResponse(
        status="error",
        message="Invalid query mode",
    )


def execute_broadcast_query(
    avatar_ids: list[int],
    query: str,
    query_mode: AvatarQueryMode,
    requester: User,
    db_session: Session,
) -> dict[int, AvatarQueryResponse]:
    """Execute a query against multiple avatars.

    Args:
        avatar_ids: List of avatar IDs to query
        query: The search query text
        query_mode: Whether to search owned documents or all accessible documents
        requester: The user making the request
        db_session: Database session

    Returns:
        Dictionary mapping avatar_id to AvatarQueryResponse
    """
    results = {}
    for avatar_id in avatar_ids:
        results[avatar_id] = execute_avatar_query(
            avatar_id=avatar_id,
            query=query,
            query_mode=query_mode,
            requester=requester,
            db_session=db_session,
        )
    return results
