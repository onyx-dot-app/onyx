from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db import kg_config
from onyx.db.engine import get_session
from onyx.db.entity_type import get_configured_entity_types
from onyx.db.entity_type import update_entity_types_and_related_connectors__commit
from onyx.db.models import User
from onyx.db.persona import create_update_persona
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import mark_persona_as_not_deleted
from onyx.kg.resets.reset_index import reset_full_kg_index__commit
from onyx.kg.setup.kg_default_entity_definitions import (
    populate_missing_default_entity_types__commit,
)
from onyx.prompts.kg_prompts import KG_BETA_ASSISTANT_SYSTEM_PROMPT
from onyx.prompts.kg_prompts import KG_BETA_ASSISTANT_TASK_PROMPT
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.kg.models import DisableKGConfigRequest
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import EntityType
from onyx.server.kg.models import KGConfig
from onyx.server.kg.models import KGConfig as KGConfigAPIModel
from onyx.tools.built_in_tools import get_search_tool


_KG_BETA_ASSISTANT_DESCRIPTION = "The KG Beta assistant uses the Onyx Knowledge Graph (beta) structure \
to answer questions"

admin_router = APIRouter(prefix="/admin/kg")


# exposed
# Controls whether or not kg is viewable in the first place.


@admin_router.get("/exposed")
def get_kg_exposed(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> bool:
    return kg_config.get_kg_exposed(db_session=db_session)


# global resets


@admin_router.put("/reset")
def reset_kg(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[EntityType]:
    reset_full_kg_index__commit(db_session)
    populate_missing_default_entity_types__commit(db_session=db_session)
    return get_kg_entity_types(db_session=db_session)


# configurations


@admin_router.get("/config")
def get_kg_config(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> KGConfig:
    config = kg_config.get_kg_config_settings(db_session=db_session)
    return KGConfigAPIModel.from_kg_config_settings(config)


@admin_router.put("/config")
def enable_or_disable_kg(
    req: EnableKGConfigRequest | DisableKGConfigRequest,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    if isinstance(req, DisableKGConfigRequest):
        # Get the KG Beta persona ID and delete it
        persona_id = kg_config.get_kg_beta_persona_id(db_session=db_session)
        if persona_id:
            mark_persona_as_deleted(
                persona_id=persona_id,
                user=user,
                db_session=db_session,
            )
        kg_config.disable_kg__commit(db_session=db_session)
        return

    # Enable KG
    kg_config.enable_kg__commit(db_session=db_session, enable_req=req)
    populate_missing_default_entity_types__commit(db_session=db_session)

    # Create or restore KG Beta persona

    # Get the search tool
    search_tool = get_search_tool(db_session=db_session)
    if not search_tool:
        raise RuntimeError("SearchTool not found in the database.")

    # Check if we have a previously created persona
    persona_id = kg_config.get_kg_beta_persona_id(db_session=db_session)

    if persona_id is not None:
        # Try to restore the existing persona
        try:
            persona = get_persona_by_id(
                persona_id=persona_id,
                user=user,
                db_session=db_session,
                include_deleted=True,
            )
            if persona.deleted:
                mark_persona_as_not_deleted(
                    persona_id=persona_id,
                    user=user,
                    db_session=db_session,
                )
            return

        except ValueError:
            # If persona doesn't exist or can't be restored, create a new one below
            pass

    # Create KG Beta persona
    user_ids = [user.id] if user else []
    is_public = len(user_ids) == 0

    persona_request = PersonaUpsertRequest(
        name="KG Beta",
        description=_KG_BETA_ASSISTANT_DESCRIPTION,
        system_prompt=KG_BETA_ASSISTANT_SYSTEM_PROMPT,
        task_prompt=KG_BETA_ASSISTANT_TASK_PROMPT,
        datetime_aware=False,
        include_citations=True,
        num_chunks=25,
        llm_relevance_filter=False,
        is_public=is_public,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.NO_DECAY,
        prompt_ids=[0],
        document_set_ids=[],
        tool_ids=[search_tool.id],
        llm_model_provider_override=None,
        llm_model_version_override=None,
        starter_messages=None,
        users=user_ids,
        groups=[],
        label_ids=[],
        is_default_persona=False,
        display_priority=0,
        user_file_ids=[],
        user_folder_ids=[],
    )

    persona_snapshot = create_update_persona(
        persona_id=None,
        create_persona_request=persona_request,
        user=user,
        db_session=db_session,
    )
    # Store the persona ID in the KG config
    kg_config.set_kg_beta_persona_id(
        db_session=db_session, persona_id=persona_snapshot.id
    )


# entity-types


@admin_router.get("/entity-types")
def get_kg_entity_types(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[EntityType]:
    # when using for the first time, populate with default entity types
    kg_entity_types = get_configured_entity_types(db_session=db_session)

    return [EntityType.from_model(kg_entity_type) for kg_entity_type in kg_entity_types]


@admin_router.put("/entity-types")
def update_kg_entity_types(
    updates: list[EntityType],
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_entity_types_and_related_connectors__commit(
        db_session=db_session, updates=updates
    )
