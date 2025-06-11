from typing import Union

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db import kg_config
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.server.kg.models import DisableKGConfigRequest
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import EntityType
from onyx.server.kg.models import KGConfig

admin_router = APIRouter(prefix="/admin/kg")


@admin_router.get("/exposed")
def get_kg_exposed(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> bool:
    return kg_config.get_kg_exposed(db_session=db_session)


@admin_router.put("/reset")
def reset_kg(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    kg_config.reset_kg(db_session=db_session)


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
    else:
        kg_config.disable_kg(db_session=db_session)


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
