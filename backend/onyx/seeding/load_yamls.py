import yaml
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import INPUT_PROMPT_YAML
from onyx.configs.chat_configs import USER_FOLDERS_YAML
from onyx.db.input_prompt import insert_input_prompt_if_not_exists
from onyx.db.persona import delete_old_default_personas
from onyx.db.persona import upsert_persona
from onyx.db.user_documents import upsert_user_folder
from onyx.seeding.prebuilt_personas import get_prebuilt_personas
from onyx.tools.built_in_tools import get_builtin_tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
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
    """Load built-in personas with embedded prompt configuration."""
    logger.info("Loading builtin personas")
    try:
        for prebuilt_persona in get_prebuilt_personas():
            # Handle tool IDs for image generation
            tool_ids = None
            if prebuilt_persona.image_generation:
                image_tool = get_builtin_tool(db_session, ImageGenerationTool)
                if image_tool:
                    tool_ids = [image_tool.id]
                else:
                    raise ValueError(
                        f"Image generation tool not found: {ImageGenerationTool._NAME}"
                    )

            # Create or update the persona
            persona = upsert_persona(
                user=None,
                # make negative to not clash with user-created personas
                persona_id=(
                    (-1 * prebuilt_persona.id)
                    if prebuilt_persona.id is not None
                    else None
                ),
                name=prebuilt_persona.name,
                description=prebuilt_persona.description,
                num_chunks=prebuilt_persona.num_chunks,
                chunks_above=prebuilt_persona.chunks_above,
                chunks_below=prebuilt_persona.chunks_below,
                llm_relevance_filter=prebuilt_persona.llm_relevance_filter,
                llm_filter_extraction=prebuilt_persona.llm_filter_extraction,
                recency_bias=prebuilt_persona.recency_bias,
                llm_model_provider_override=prebuilt_persona.llm_model_provider_override,
                llm_model_version_override=prebuilt_persona.llm_model_version_override,
                starter_messages=prebuilt_persona.starter_messages,
                system_prompt=prebuilt_persona.system_prompt,
                task_prompt=prebuilt_persona.task_prompt,
                datetime_aware=prebuilt_persona.datetime_aware,
                is_public=True,
                builtin_persona=True,
                is_default_persona=prebuilt_persona.is_default_persona,
                is_visible=prebuilt_persona.is_visible,
                display_priority=prebuilt_persona.display_priority,
                icon_color=prebuilt_persona.icon_color,
                icon_shape=prebuilt_persona.icon_shape,
                tool_ids=tool_ids,
                db_session=db_session,
                commit=False,
            )

            # Set the prompt fields directly on the persona object
            # These are now embedded in the persona table after the migration
            persona.system_prompt = prebuilt_persona.system_prompt
            persona.task_prompt = prebuilt_persona.task_prompt
            persona.datetime_aware = prebuilt_persona.datetime_aware

        db_session.commit()
        logger.info(
            f"Successfully loaded {len(get_prebuilt_personas())} builtin personas"
        )
    except Exception:
        db_session.rollback()
        logger.exception("Error loading builtin personas")
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
