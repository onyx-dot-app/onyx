from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import Persona
from onyx.db.models import UserFile
from onyx.db.projects import get_user_files_from_project
from onyx.db.user_file import update_last_accessed_at_for_user_files
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import get_user_files_as_user
from onyx.file_store.utils import load_in_memory_chat_files
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.utils.logger import setup_logger


logger = setup_logger()


def parse_user_files(
    user_file_ids: list[UUID],
    db_session: Session,
    persona: Persona,
    actual_user_input: str,
    project_id: int | None,
    # should only be None if auth is disabled
    user_id: UUID | None,
) -> tuple[list[InMemoryChatFile], list[UserFile], SearchToolOverrideKwargs | None]:
    """
    Parse user files and project into in-memory chat files and create search tool override kwargs.
    Only creates SearchToolOverrideKwargs if token overflow occurs.

    Args:
        user_file_ids: List of user file IDs to load
        db_session: Database session
        persona: Persona to calculate available tokens
        actual_user_input: User's input message for token calculation
        project_id: Project ID to validate file ownership
        user_id: User ID to validate file ownership

    Returns:
        Tuple of (
            loaded user files,
            user file models,
            search tool override kwargs if token
                overflow
        )
    """
    # Return empty results if no files or project specified
    if not user_file_ids and not project_id:
        return [], [], None

    project_user_file_ids = []

    if project_id:
        project_user_file_ids.extend(
            [
                file.id
                for file in get_user_files_from_project(project_id, user_id, db_session)
            ]
        )

    # Combine user-provided and project-derived user file IDs
    combined_user_file_ids = user_file_ids + project_user_file_ids or []

    # Load user files from the database into memory
    user_files = load_in_memory_chat_files(
        combined_user_file_ids,
        db_session,
    )

    user_file_models = get_user_files_as_user(
        combined_user_file_ids,
        user_id,
        db_session,
    )

    # Update last accessed at for the user files which are used in the chat
    if user_file_ids or project_user_file_ids:
        # update_last_accessed_at_for_user_files expects list[UUID]
        update_last_accessed_at_for_user_files(
            combined_user_file_ids,
            db_session,
        )

    # Calculate token count for the files, need to import here to avoid circular import
    # TODO: fix this
    from onyx.db.user_file import calculate_user_files_token_count
    from onyx.chat.prompt_builder.citations_prompt import (
        compute_max_document_tokens_for_persona,
    )

    # calculate_user_files_token_count now expects list[UUID]
    total_tokens = calculate_user_files_token_count(
        combined_user_file_ids,
        db_session,
    )

    # Calculate available tokens for documents based on prompt, user input, etc.
    available_tokens = compute_max_document_tokens_for_persona(
        persona=persona,
        actual_user_input=actual_user_input,
    )
    uploaded_context_cap = int(available_tokens * 0.5)

    logger.debug(
        f"Total file tokens: {total_tokens}, Available tokens: {available_tokens},"
        f"Allowed uploaded context tokens: {uploaded_context_cap}"
    )

    have_enough_tokens = total_tokens <= uploaded_context_cap

    # If we have enough tokens, we don't need search
    # we can just pass them into the prompt directly
    if have_enough_tokens:
        # No search tool override needed - files can be passed directly
        return user_files, user_file_models, None

    # Token overflow - need to use search tool
    override_kwargs = SearchToolOverrideKwargs(
        force_no_rerank=have_enough_tokens,
        alternate_db_session=None,
        retrieved_sections_callback=None,
        skip_query_analysis=have_enough_tokens,
        user_file_ids=user_file_ids or [],
        project_id=(
            project_id if persona.is_default_persona else None
        ),  # if the persona is not default, we don't want to use the project files
    )

    return user_files, user_file_models, override_kwargs
