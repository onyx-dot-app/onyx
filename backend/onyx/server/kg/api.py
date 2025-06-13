from typing import Union

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db import kg_config
from onyx.db.engine import get_session
from onyx.db.kg_config import reset_entity_types
from onyx.db.models import User
from onyx.db.persona import create_update_persona
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import mark_persona_as_not_deleted
from onyx.db.prompts import build_prompt_name_from_persona_name
from onyx.db.prompts import upsert_prompt
from onyx.kg.resets.reset_index import reset_full_kg_index
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.kg.models import DisableKGConfigRequest
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import EntityType
from onyx.server.kg.models import KGConfig
from onyx.tools.built_in_tools import get_search_tool

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
    # reset all entity types to inactive
    default_entities = reset_entity_types(db_session=db_session)

    # TODO: before merging, convert to celery task function in other PR
    reset_full_kg_index()

    return default_entities


# configurations


@admin_router.get("/config")
def get_kg_config(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> KGConfig:
    return kg_config.get_kg_config(db_session=db_session)


@admin_router.put("/config")
def enable_or_disable_kg(
    req: Union[EnableKGConfigRequest, DisableKGConfigRequest],
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    if isinstance(req, EnableKGConfigRequest):
        enable_req = req if req.enabled else None
    elif isinstance(req, DisableKGConfigRequest):
        if req.enabled:
            raise ValueError("Cannot update KG Config with only `enabled: true`")
        enable_req = None
    else:
        raise ValueError("Invalid request body")

    if enable_req:
        kg_config.enable_kg(db_session=db_session, enable_req=enable_req)
        # Create or restore KG Beta persona
        # Create prompt for KG Beta
        prompt = upsert_prompt(
            db_session=db_session,
            user=None,
            name=build_prompt_name_from_persona_name("KG Beta"),
            system_prompt=(
                "You are a knowledge graph assistant that helps users explore and "
                "understand relationships between entities."
            ),
            task_prompt=(
                "Help users explore and understand the knowledge graph by answering "
                "questions about entities and their relationships."
            ),
            datetime_aware=False,
            include_citations=True,
            prompt_id=None,
        )

        # Get the search tool
        search_tool = get_search_tool(db_session=db_session)
        if not search_tool:
            raise RuntimeError("SearchTool not found in the database.")

        # Check if we have a previously created persona
        persona_id = kg_config.get_kg_beta_persona_id(db_session=db_session)
        try:
            if persona_id:
                # Try to restore the existing persona
                try:
                    persona = get_persona_by_id(
                        persona_id=persona_id,
                        user=None,
                        db_session=db_session,
                        include_deleted=True,
                    )
                    if persona.deleted:
                        mark_persona_as_not_deleted(
                            persona_id=persona_id,
                            user=None,
                            db_session=db_session,
                        )
                    return
                except ValueError:
                    # If persona doesn't exist or can't be restored, create a new one
                    pass
        except Exception:
            # If any error occurs, create a new persona
            pass

        # Create KG Beta persona
        persona_request = PersonaUpsertRequest(
            name="KG Beta",
            description=(
                "The KG Beta assistant uses the Onyx Knowledge Graph (beta) structure "
                "to answer questions"
            ),
            system_prompt="Use the Onyx Knowledge Graph (beta) to answer questions.",
            task_prompt="",
            datetime_aware=False,
            include_citations=True,
            num_chunks=25,
            llm_relevance_filter=False,
            is_public=False,
            llm_filter_extraction=False,
            recency_bias=RecencyBiasSetting.NO_DECAY,
            prompt_ids=[prompt.id],
            document_set_ids=[],
            tool_ids=[search_tool.id],
            llm_model_provider_override=None,
            llm_model_version_override=None,
            starter_messages=None,
            users=[],
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
            user=None,
            db_session=db_session,
        )
        # Store the persona ID in the KG config
        kg_config.set_kg_beta_persona_id(
            db_session=db_session, persona_id=persona_snapshot.id
        )
    else:
        # Get the KG Beta persona ID and delete it
        persona_id = kg_config.get_kg_beta_persona_id(db_session=db_session)
        if persona_id:
            mark_persona_as_deleted(
                persona_id=persona_id,
                user=None,
                db_session=db_session,
            )
        kg_config.disable_kg(db_session=db_session)


# entity-types


@admin_router.get("/entity-types")
def get_kg_entity_types(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[EntityType]:
    return kg_config.get_kg_entity_types(
        db_session=db_session,
    )


@admin_router.put("/entity-types")
def update_kg_entity_types(
    updates: list[EntityType],
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    kg_config.update_kg_entity_types(db_session=db_session, updates=updates)
