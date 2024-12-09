import yaml
from sqlalchemy.orm import Session

from danswer.configs.chat_configs import INPUT_PROMPT_YAML
from danswer.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from danswer.configs.chat_configs import PERSONAS_YAML
from danswer.configs.chat_configs import PROMPTS_YAML
from danswer.context.search.enums import RecencyBiasSetting
from danswer.db.document_set import get_or_create_document_set_by_name
from danswer.db.input_prompt import insert_input_prompt_if_not_exists
from danswer.db.models import DocumentSet as DocumentSetDBModel
from danswer.db.models import Persona
from danswer.db.models import Prompt as PromptDBModel
from danswer.db.models import Tool as ToolDBModel
from danswer.db.persona import get_prompt_by_name
from danswer.db.persona import upsert_persona
from danswer.db.persona import upsert_prompt


def load_prompts_from_yaml(
    db_session: Session, prompts_yaml: str = PROMPTS_YAML
) -> None:
    with open(prompts_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_prompts = data.get("prompts", [])
    for prompt in all_prompts:
        upsert_prompt(
            user=None,
            prompt_id=prompt.get("id"),
            name=prompt["name"],
            description=prompt["description"].strip(),
            system_prompt=prompt["system"].strip(),
            task_prompt=prompt["task"].strip(),
            include_citations=prompt["include_citations"],
            datetime_aware=prompt.get("datetime_aware", True),
            default_prompt=True,
            personas=None,
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

        prompt_ids: list[int] | None = None
        prompt_set_names = persona["prompts"]
        if prompt_set_names:
            prompts: list[PromptDBModel | None] = [
                get_prompt_by_name(prompt_name, user=None, db_session=db_session)
                for prompt_name in prompt_set_names
            ]
            if any([prompt is None for prompt in prompts]):
                raise ValueError("Invalid Persona configs, not all prompts exist")

            if prompts:
                prompt_ids = [prompt.id for prompt in prompts if prompt is not None]

        p_id = persona.get("id")
        tool_ids = []
        if persona.get("image_generation"):
            image_gen_tool = (
                db_session.query(ToolDBModel)
                .filter(ToolDBModel.name == "ImageGenerationTool")
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

        upsert_persona(
            user=None,
            persona_id=(-1 * p_id) if p_id is not None else None,
            name=persona["name"],
            description=persona["description"],
            num_chunks=persona.get("num_chunks")
            if persona.get("num_chunks") is not None
            else default_chunks,
            llm_relevance_filter=persona.get("llm_relevance_filter"),
            starter_messages=persona.get("starter_messages"),
            llm_filter_extraction=persona.get("llm_filter_extraction"),
            icon_shape=persona.get("icon_shape"),
            icon_color=persona.get("icon_color"),
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            recency_bias=RecencyBiasSetting(persona["recency_bias"]),
            prompt_ids=prompt_ids,
            document_set_ids=doc_set_ids,
            tool_ids=tool_ids,
            builtin_persona=True,
            is_public=True,
            display_priority=existing_persona.display_priority
            if existing_persona is not None
            else persona.get("display_priority"),
            is_visible=existing_persona.is_visible
            if existing_persona is not None
            else persona.get("is_visible"),
            db_session=db_session,
        )


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


def load_chat_yamls(
    db_session: Session,
    prompt_yaml: str = PROMPTS_YAML,
    personas_yaml: str = PERSONAS_YAML,
    input_prompts_yaml: str = INPUT_PROMPT_YAML,
) -> None:
    load_prompts_from_yaml(db_session, prompt_yaml)
    load_personas_from_yaml(db_session, personas_yaml)
    load_input_prompts_from_yaml(db_session, input_prompts_yaml)
