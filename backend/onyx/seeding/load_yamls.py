import yaml
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import INPUT_PROMPT_YAML
from onyx.configs.chat_configs import USER_FOLDERS_YAML
from onyx.db.input_prompt import insert_input_prompt_if_not_exists
from onyx.db.persona import delete_old_default_personas
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import upsert_persona
from onyx.db.user_documents import upsert_user_folder
from onyx.seeding.default_persona import apply_always_updated_fields
from onyx.seeding.default_persona import get_default_persona
from onyx.tools.built_in_tools import get_builtin_tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    WebSearchTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger


logger = setup_logger()


def load_user_folders_from_yaml(
    db_session: Session,
    user_folders_yaml: str = USER_FOLDERS_YAML,
) -> None:
    with open(user_folders_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_user_folders = data.get("user_folders", [])
    for user_folder in all_user_folders:
        upsert_user_folder(
            db_session=db_session,
            id=user_folder.get("id"),
            name=user_folder.get("name"),
            description=user_folder.get("description"),
            created_at=user_folder.get("created_at"),
            user=user_folder.get("user"),
            files=user_folder.get("files"),
            assistants=user_folder.get("assistants"),
        )
    db_session.flush()


def load_input_prompts_from_yaml(
    db_session: Session, input_prompts_yaml: str = INPUT_PROMPT_YAML
) -> None:
    with open(input_prompts_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_input_prompts = data.get("input_prompts", [])
    for input_prompt in all_input_prompts:
        # If these prompts are deleted (which is a hard delete in the DB), on server startup
        # they will be recreated, but the user can always just deactivate them, just a light inconvenience

        insert_input_prompt_if_not_exists(
            user=None,
            input_prompt_id=input_prompt.get("id"),
            prompt=input_prompt["prompt"],
            content=input_prompt["content"],
            is_public=input_prompt["is_public"],
            active=input_prompt.get("active", True),
            db_session=db_session,
            commit=True,
        )


def load_builtin_personas(db_session: Session) -> None:
    """Load default personas with selective field updates.

    - Always updates core system fields (name, description, prompts, flags)
    - Only sets admin-controlled fields on initial creation
    - Preserves admin modifications to tunable parameters
    """
    logger.info("Loading default personas")
    try:
        default_persona = get_default_persona()
        try:
            existing_persona = get_persona_by_id(
                persona_id=default_persona.id,
                user=None,
                db_session=db_session,
                include_deleted=True,
                is_for_edit=True,
            )
            # handle case where empty persona exists
            if not existing_persona.name:
                existing_persona = None
        except Exception:
            existing_persona = None

        # Prepare admin-controlled fields and tool_ids based on existence
        if not existing_persona:
            # New persona: set admin-controlled fields from defaults
            tool_ids_list: list[int] = []

            internal_search_tool = get_builtin_tool(db_session, SearchTool)
            if internal_search_tool:
                tool_ids_list.append(internal_search_tool.id)
            else:
                raise ValueError(f"Internal search tool not found: {SearchTool._NAME}")

            image_tool = get_builtin_tool(db_session, ImageGenerationTool)
            if image_tool:
                tool_ids_list.append(image_tool.id)
            else:
                raise ValueError(
                    f"Image generation tool not found: {ImageGenerationTool._NAME}"
                )

            try:
                web_search_tool = get_builtin_tool(db_session, WebSearchTool)
                if web_search_tool:
                    tool_ids_list.append(web_search_tool.id)
            except Exception:
                # Do not fail loading personas if internet search providers are not configured
                # TODO: always attach once web search is configurable in the UI
                logger.info(
                    "WebSearchTool not available; skipping attaching to default persona"
                )

            tool_ids = tool_ids_list or None

            num_chunks = default_persona.num_chunks
            chunks_above = default_persona.chunks_above
            chunks_below = default_persona.chunks_below
            llm_relevance_filter = default_persona.llm_relevance_filter
            llm_filter_extraction = default_persona.llm_filter_extraction
            recency_bias = default_persona.recency_bias
            llm_model_provider_override = default_persona.llm_model_provider_override
            llm_model_version_override = default_persona.llm_model_version_override
            starter_messages = default_persona.starter_messages
            is_visible = default_persona.is_visible
            display_priority = default_persona.display_priority
            icon_color = default_persona.icon_color
            icon_shape = default_persona.icon_shape
        else:
            # Existing persona: refresh always-updated fields, preserve admin-controlled fields
            existing_persona = apply_always_updated_fields(
                existing_persona, default_persona
            )

            tool_ids = [tool.id for tool in existing_persona.tools]
            num_chunks = (
                existing_persona.num_chunks
                if existing_persona.num_chunks is not None
                else default_persona.num_chunks
            )
            chunks_above = (
                existing_persona.chunks_above
                if existing_persona.chunks_above is not None
                else default_persona.chunks_above
            )
            chunks_below = (
                existing_persona.chunks_below
                if existing_persona.chunks_below is not None
                else default_persona.chunks_below
            )
            llm_relevance_filter = (
                existing_persona.llm_relevance_filter
                if existing_persona.llm_relevance_filter is not None
                else default_persona.llm_relevance_filter
            )
            llm_filter_extraction = (
                existing_persona.llm_filter_extraction
                if existing_persona.llm_filter_extraction is not None
                else default_persona.llm_filter_extraction
            )
            recency_bias = (
                existing_persona.recency_bias
                if existing_persona.recency_bias is not None
                else default_persona.recency_bias
            )
            llm_model_provider_override = (
                existing_persona.llm_model_provider_override
                if existing_persona.llm_model_provider_override is not None
                else default_persona.llm_model_provider_override
            )
            llm_model_version_override = (
                existing_persona.llm_model_version_override
                if existing_persona.llm_model_version_override is not None
                else default_persona.llm_model_version_override
            )
            starter_messages = (
                existing_persona.starter_messages
                if existing_persona.starter_messages is not None
                else default_persona.starter_messages
            )
            is_visible = (
                existing_persona.is_visible
                if existing_persona.is_visible is not None
                else default_persona.is_visible
            )
            display_priority = (
                existing_persona.display_priority
                if existing_persona.display_priority is not None
                else default_persona.display_priority
            )
            icon_color = (
                existing_persona.icon_color
                if existing_persona.icon_color is not None
                else default_persona.icon_color
            )
            icon_shape = (
                existing_persona.icon_shape
                if existing_persona.icon_shape is not None
                else default_persona.icon_shape
            )

        # Single upsert call with appropriate fields
        upsert_persona(
            user=None,
            persona_id=default_persona.id,
            # Always updated fields
            name=(existing_persona.name if existing_persona else default_persona.name),
            description=(
                existing_persona.description
                if existing_persona
                else default_persona.description
            ),
            system_prompt=(
                existing_persona.system_prompt
                if existing_persona
                else default_persona.system_prompt
            ),
            task_prompt=(
                existing_persona.task_prompt
                if existing_persona
                else default_persona.task_prompt
            ),
            datetime_aware=(
                existing_persona.datetime_aware
                if existing_persona
                else default_persona.datetime_aware
            ),
            builtin_persona=(
                existing_persona.builtin_persona
                if existing_persona
                else default_persona.builtin_persona
            ),
            is_default_persona=(
                existing_persona.is_default_persona
                if existing_persona
                else default_persona.is_default_persona
            ),
            # Admin-controlled fields (conditional)
            num_chunks=num_chunks,
            chunks_above=chunks_above,
            chunks_below=chunks_below,
            llm_relevance_filter=llm_relevance_filter,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            starter_messages=starter_messages,
            is_visible=is_visible,
            display_priority=display_priority,
            icon_color=icon_color,
            icon_shape=icon_shape,
            tool_ids=tool_ids,
            # Common fields
            is_public=True,
            db_session=db_session,
            commit=False,
        )

        if not existing_persona:
            logger.info(f"Created new default persona: {default_persona.name}")
        else:
            logger.info(
                f"Updated system fields for existing default persona: {default_persona.name}"
            )

        db_session.commit()
        logger.info("Successfully loaded default persona")
    except Exception:
        db_session.rollback()
        logger.exception("Error loading default persona")
        raise


def load_chat_yamls(
    db_session: Session,
    input_prompts_yaml: str = INPUT_PROMPT_YAML,
) -> None:
    """Load all chat-related YAML configurations and builtin personas."""
    load_input_prompts_from_yaml(db_session, input_prompts_yaml)
    load_user_folders_from_yaml(db_session)

    # cleanup old default personas before loading
    delete_old_default_personas(db_session)
    load_builtin_personas(db_session)
