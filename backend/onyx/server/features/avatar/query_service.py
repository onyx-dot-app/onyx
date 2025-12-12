"""
Avatar query service for executing searches against avatars.

This module handles the core logic for querying avatars, including:
- Owned documents mode (instant, no permission required)
- Accessible documents mode (requires permission if answer found)
- Permission request creation and caching
"""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
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
from onyx.db.enums import AvatarQueryMode
from onyx.db.models import Avatar
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.server.features.avatar.models import AvatarQueryResponse
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


# Minimum score threshold for considering results "good enough"
MIN_RESULT_SCORE = 0.3
# Minimum number of chunks needed to consider a query successful
MIN_CHUNKS_FOR_ANSWER = 1


def _build_owned_documents_filters(
    avatar: Avatar,
) -> IndexFilters:
    """Build filters for querying documents owned by the avatar's user."""
    return IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        access_control_list=None,  # No ACL filtering for owned docs
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
) -> str | None:
    """Generate an answer from the retrieved chunks.

    For now, this returns a simple summary of the found documents.
    In production, this should use the LLM to generate a proper answer.
    """
    if not chunks:
        return None

    # Build a simple summary of found content
    summary_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        source = chunk.semantic_identifier or chunk.document_id
        preview = (
            chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
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
        filters = _build_owned_documents_filters(avatar)
        chunks = _execute_search(query, filters, db_session)

        if not _has_good_results(chunks):
            return AvatarQueryResponse(
                status="no_results",
                message="No relevant documents found",
            )

        # Generate answer from chunks
        answer = _generate_answer(query, chunks)

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

            answer = _generate_answer(query, chunks)

            return AvatarQueryResponse(
                status="success",
                answer=answer,
                source_document_ids=[chunk.document_id for chunk in chunks],
            )

        # Preview query to check if good answer exists
        filters = _build_accessible_documents_filters(avatar, db_session)
        chunks = _execute_search(query, filters, db_session)

        if not _has_good_results(chunks):
            # No good results - don't create permission request
            return AvatarQueryResponse(
                status="no_results",
                message="No relevant documents found",
            )

        # Generate and cache the answer
        cached_answer = _generate_answer(query, chunks)
        cached_doc_ids = [chunk.chunk_id for chunk in chunks[:10]]

        # Calculate answer quality score (simple heuristic based on top chunk scores)
        if chunks and chunks[0].score:
            answer_quality = sum(c.score or 0 for c in chunks[:3]) / min(3, len(chunks))
        else:
            answer_quality = None

        # Create permission request with cached answer
        permission_request = create_permission_request(
            avatar_id=avatar_id,
            requester_id=requester.id,
            query_text=query if avatar.show_query_in_request else None,
            db_session=db_session,
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            cached_answer=cached_answer,
            cached_search_doc_ids=cached_doc_ids,
            answer_quality_score=answer_quality,
        )

        # Notify the avatar owner
        create_notification(
            user_id=avatar.user_id,
            notif_type=NotificationType.AVATAR_PERMISSION_REQUEST,
            db_session=db_session,
            additional_data={
                "request_id": permission_request.id,
                "requester_email": requester.email,
                "query_preview": query[:100] if avatar.show_query_in_request else None,
            },
        )

        db_session.commit()

        return AvatarQueryResponse(
            status="pending_permission",
            permission_request_id=permission_request.id,
            message="Your request has been sent to the avatar owner for approval",
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
