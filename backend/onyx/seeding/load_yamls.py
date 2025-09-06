import yaml
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import INPUT_PROMPT_YAML
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.chat_configs import PERSONAS_YAML
from onyx.configs.chat_configs import PROMPTS_YAML
from onyx.configs.chat_configs import USER_FOLDERS_YAML
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.document_set import get_or_create_document_set_by_name
from onyx.db.input_prompt import insert_input_prompt_if_not_exists
from onyx.db.models import DocumentSet as DocumentSetDBModel
from onyx.db.models import Persona
from onyx.db.models import Tool as ToolDBModel
from onyx.db.persona import upsert_persona
from onyx.db.user_documents import upsert_user_folder
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)


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


def load_prompts_from_yaml(
    db_session: Session, prompts_yaml: str = PROMPTS_YAML
) -> None:
    """Load prompts as personas with embedded prompt configuration.

    Since prompts are now embedded in personas, this function creates
    personas with the prompt configuration embedded directly.
    """
    with open(prompts_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_prompts = data.get("prompts", [])
    for prompt in all_prompts:
        # Create a persona, then set embedded prompt configuration
        persona = upsert_persona(
            user=None,
            persona_id=(
                (-1 * prompt.get("id")) if prompt.get("id") is not None else None
            ),
            name=prompt["name"],
            description=prompt["description"].strip(),
            num_chunks=MAX_CHUNKS_FED_TO_CHAT,
            llm_relevance_filter=False,
            llm_filter_extraction=False,
            recency_bias=RecencyBiasSetting.BASE_DECAY,
            llm_model_provider_override=None,
            llm_model_version_override=None,
            starter_messages=None,
            builtin_persona=True,
            is_public=True,
            db_session=db_session,
        )
        persona.system_prompt = prompt["system"].strip()
        persona.task_prompt = prompt["task"].strip()
        persona.include_citations = prompt["include_citations"]
        persona.datetime_aware = prompt.get("datetime_aware", True)
        persona.is_default_prompt = True
        db_session.commit()


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


def load_personas_from_yaml(
    db_session: Session,
    personas_yaml: str = PERSONAS_YAML,
    default_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
) -> None:
    with open(personas_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_personas = data.get("personas", [])

    for persona in all_personas:
        doc_set_names = persona["document_sets"]
        doc_sets: list[DocumentSetDBModel] = [
            get_or_create_document_set_by_name(db_session, name)
            for name in doc_set_names
        ]

        # Assume if user hasn't set any document sets for the persona, the user may want
        # to later attach document sets to the persona manually, therefore, don't overwrite/reset
        # the document sets for the persona
        doc_set_ids: list[int] | None = None
        if doc_sets:
            doc_set_ids = [doc_set.id for doc_set in doc_sets]
        else:
            doc_set_ids = None

        # Handle embedded prompt configuration
        # For now, we'll use the first prompt from the YAML or require explicit prompt fields
        prompt_config = persona.get("prompt_config", {})
        if not prompt_config and persona.get("prompts"):
            # If legacy format with prompt names, we'll need to look up the first one
            # and use its configuration, but this is a temporary compatibility measure
            prompt_set_names = persona["prompts"]
            if prompt_set_names:
                # For now, use default prompt configuration - in production you might want to
                # look up the actual prompt configuration from a mapping or separate YAML
                prompt_config = {
                    "system_prompt": "You are a helpful AI assistant.",
                    "task_prompt": "Please answer the user's question based on the provided context.",
                    "include_citations": True,
                    "datetime_aware": True,
                }

        p_id = persona.get("id")
        tool_ids = []

        if persona.get("image_generation"):
            image_gen_tool = (
                db_session.query(ToolDBModel)
                .filter(ToolDBModel.name == ImageGenerationTool.__name__)
                .first()
            )
            if image_gen_tool:
                tool_ids.append(image_gen_tool.id)

        llm_model_provider_override = persona.get("llm_model_provider_override")
        llm_model_version_override = persona.get("llm_model_version_override")

        # Set specific overrides for image generation persona
        if persona.get("image_generation"):
            llm_model_version_override = "gpt-4o"

        existing_persona = (
            db_session.query(Persona).filter(Persona.name == persona["name"]).first()
        )

        persona_model = upsert_persona(
            user=None,
            persona_id=(-1 * p_id) if p_id is not None else None,
            name=persona["name"],
            description=persona["description"],
            num_chunks=(
                persona.get("num_chunks")
                if persona.get("num_chunks") is not None
                else default_chunks
            ),
            llm_relevance_filter=persona.get("llm_relevance_filter"),
            starter_messages=persona.get("starter_messages", []),
            llm_filter_extraction=persona.get("llm_filter_extraction"),
            icon_shape=persona.get("icon_shape"),
            icon_color=persona.get("icon_color"),
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            recency_bias=RecencyBiasSetting(persona["recency_bias"]),
            document_set_ids=doc_set_ids,
            tool_ids=tool_ids,
            builtin_persona=True,
            is_public=True,
            display_priority=(
                existing_persona.display_priority
                if existing_persona is not None
                and persona.get("display_priority") is None
                else persona.get("display_priority")
            ),
            is_visible=(
                existing_persona.is_visible
                if existing_persona is not None
                else persona.get("is_visible")
            ),
            db_session=db_session,
            is_default_persona=(
                existing_persona.is_default_persona
                if existing_persona is not None
                else persona.get("is_default_persona", False)
            ),
        )
        # Set embedded prompt configuration on persona
        persona_model.system_prompt = prompt_config.get("system_prompt")
        persona_model.task_prompt = prompt_config.get("task_prompt")
        persona_model.include_citations = prompt_config.get("include_citations", True)
        persona_model.datetime_aware = prompt_config.get("datetime_aware", True)
        db_session.commit()


def load_chat_yamls(
    db_session: Session,
    prompt_yaml: str = PROMPTS_YAML,
    personas_yaml: str = PERSONAS_YAML,
    input_prompts_yaml: str = INPUT_PROMPT_YAML,
) -> None:
    load_prompts_from_yaml(db_session, prompt_yaml)
    load_personas_from_yaml(db_session, personas_yaml)
    load_input_prompts_from_yaml(db_session, input_prompts_yaml)
    load_user_folders_from_yaml(db_session)
