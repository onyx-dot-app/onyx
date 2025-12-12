"""
Celery tasks for avatar queries.

These tasks handle background processing of avatar queries,
particularly for the "All Accessible Documents" mode which can
be time-consuming and should not block the user.
"""

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import QueryExpansionType
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import get_query_embedding
from onyx.db.avatar import get_avatar_by_id
from onyx.db.avatar import get_permission_request_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AvatarPermissionRequestStatus
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.llm.factory import get_default_llms
from onyx.llm.factory import get_main_llm_from_tuple
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()

# Time limits for the task (in seconds)
AVATAR_QUERY_SOFT_TIME_LIMIT = 120  # 2 minutes
AVATAR_QUERY_TIME_LIMIT = 150  # 2.5 minutes

# Search/answer generation constants
MIN_RESULT_SCORE = 0.3
MIN_CHUNKS_FOR_ANSWER = 1

AVATAR_ANSWER_SYSTEM_PROMPT = """You are a helpful assistant answering questions based on documents \
owned by or accessible to a specific user (the "avatar").

Your task is to synthesize information from the provided document excerpts and generate a \
clear, accurate answer to the user's question.

Guidelines:
- Base your answer ONLY on the provided document excerpts
- Be concise but thorough
- If the documents don't contain enough information to fully answer the question, acknowledge what \
information is available and what is missing
- Use a professional, helpful tone
- When referencing specific information, indicate which document it came from using [1], [2], etc."""

AVATAR_ANSWER_USER_PROMPT_TEMPLATE = """Based on the following document excerpts from {avatar_name}'s \
documents, please answer this question:

Question: {query}

Document Excerpts:
{context}

Please provide a clear, helpful answer based on the information above."""


@shared_task(
    name=OnyxCeleryTask.AVATAR_QUERY_TASK,
    soft_time_limit=AVATAR_QUERY_SOFT_TIME_LIMIT,
    time_limit=AVATAR_QUERY_TIME_LIMIT,
    bind=True,
    trail=False,
)
def avatar_query_task(
    self: Task,
    *,
    permission_request_id: int,
    tenant_id: str | None = None,
) -> dict:
    """
    Background task to execute an avatar query and store the results.

    This task is used for "All Accessible Documents" mode queries.
    It executes the search, generates an answer, and updates the
    permission request with the cached results.

    Args:
        permission_request_id: The ID of the AvatarPermissionRequest to process
        tenant_id: The tenant ID for multi-tenant deployments

    Returns:
        dict with status and any error message
    """
    task_logger.info(
        f"Starting avatar query task for permission_request_id={permission_request_id}"
    )

    try:
        with get_session_with_current_tenant() as db_session:
            # Get the permission request
            request = get_permission_request_by_id(permission_request_id, db_session)
            if not request:
                task_logger.error(
                    f"Permission request {permission_request_id} not found"
                )
                return {"status": "error", "message": "Permission request not found"}

            # Verify it's in PROCESSING status
            if request.status != AvatarPermissionRequestStatus.PROCESSING:
                task_logger.warning(
                    f"Permission request {permission_request_id} is not in PROCESSING status"
                )
                return {
                    "status": "skipped",
                    "message": f"Request status is {request.status}, not PROCESSING",
                }

            # Get the avatar
            avatar = get_avatar_by_id(request.avatar_id, db_session)
            if not avatar:
                _mark_request_failed(request, db_session, "Avatar not found")
                return {"status": "error", "message": "Avatar not found"}

            # Build filters for accessible documents (query as the avatar's user)
            user_acl = build_access_filters_for_user(avatar.user, db_session)
            filters = IndexFilters(
                source_type=None,
                document_set=None,
                time_cutoff=None,
                tags=None,
                access_control_list=list(user_acl),
                tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
            )

            # Execute search
            query = request.query_text or ""
            chunks = _execute_search(query, filters, db_session)

            if not _has_good_results(chunks):
                # No good results - mark as NO_ANSWER
                request.status = AvatarPermissionRequestStatus.NO_ANSWER
                request.cached_answer = None
                db_session.commit()
                task_logger.info(
                    f"Avatar query {permission_request_id} completed with no results"
                )
                return {
                    "status": "no_results",
                    "message": "No relevant documents found",
                }

            # Generate answer
            answer = _generate_answer(query, chunks, avatar)
            cached_doc_ids = [chunk.chunk_id for chunk in chunks[:10]]

            # Calculate answer quality score
            if chunks and chunks[0].score:
                answer_quality = sum(c.score or 0 for c in chunks[:3]) / min(
                    3, len(chunks)
                )
            else:
                answer_quality = None

            # Update the request with results - set to PENDING for owner approval
            request.cached_answer = answer
            request.cached_search_doc_ids = cached_doc_ids
            request.answer_quality_score = answer_quality
            request.status = AvatarPermissionRequestStatus.PENDING
            db_session.commit()

            task_logger.info(
                f"Avatar query {permission_request_id} completed successfully"
            )
            return {"status": "success", "message": "Query completed"}

    except Exception as e:
        task_logger.error(f"Avatar query task failed: {e}")
        # Try to mark the request as failed
        try:
            with get_session_with_current_tenant() as db_session:
                request = get_permission_request_by_id(
                    permission_request_id, db_session
                )
                if (
                    request
                    and request.status == AvatarPermissionRequestStatus.PROCESSING
                ):
                    _mark_request_failed(request, db_session, str(e))
        except Exception:
            pass
        raise


def _execute_search(query: str, filters: IndexFilters, db_session) -> list:
    """Execute a hybrid search with the given filters."""

    try:
        query_embedding = get_query_embedding(query, db_session)
        document_index = get_current_primary_default_document_index(db_session)

        chunks = document_index.hybrid_retrieval(
            query=query,
            query_embedding=query_embedding,
            final_keywords=None,
            filters=filters,
            hybrid_alpha=0.5,
            time_decay_multiplier=1.0,
            num_to_retrieve=10,
            ranking_profile_type=QueryExpansionType.SEMANTIC,
        )

        return chunks[:10]
    except Exception as e:
        task_logger.error(f"Search failed: {e}")
        return []


def _has_good_results(chunks: list) -> bool:
    """Check if the search results are good enough to proceed."""
    if len(chunks) < MIN_CHUNKS_FOR_ANSWER:
        return False

    for chunk in chunks:
        if chunk.score and chunk.score >= MIN_RESULT_SCORE:
            return True

    return len(chunks) >= MIN_CHUNKS_FOR_ANSWER


def _generate_answer(query: str, chunks: list, avatar) -> str | None:
    """Generate an answer from the retrieved chunks using the LLM."""
    if not chunks:
        return None

    # Build context from chunks
    context_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        source = chunk.semantic_identifier or chunk.document_id
        context_parts.append(f"[{i}] Source: {source}\n{chunk.content}")

    context = "\n\n---\n\n".join(context_parts)
    avatar_name = avatar.name or avatar.user.email

    user_prompt = AVATAR_ANSWER_USER_PROMPT_TEMPLATE.format(
        avatar_name=avatar_name,
        query=query,
        context=context,
    )

    try:
        llms = get_default_llms()
        llm = get_main_llm_from_tuple(llms)

        system_msg: SystemMessage = {
            "role": "system",
            "content": AVATAR_ANSWER_SYSTEM_PROMPT,
        }
        user_msg: UserMessageWithText = {
            "role": "user",
            "content": user_prompt,
        }

        response = llm.invoke([system_msg, user_msg])

        if response and response.choice and response.choice.message:
            content = response.choice.message.content
            if content:
                return content

        return None

    except Exception as e:
        task_logger.error(f"Failed to generate LLM answer: {e}")
        # Fall back to simple summary
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


def _mark_request_failed(request, db_session, error_message: str) -> None:
    """Mark a request as failed (NO_ANSWER status with error in denial_reason)."""
    request.status = AvatarPermissionRequestStatus.NO_ANSWER
    request.denial_reason = f"Processing failed: {error_message}"
    db_session.commit()
