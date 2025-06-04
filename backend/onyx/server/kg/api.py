from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine import get_session
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import update_kg_config_settings
from onyx.db.models import User
from onyx.kg.models import KGConfigSettings

admin_router = APIRouter(prefix="/admin/kg")


@admin_router.get("/configs")
def get_kg_configs(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> KGConfigSettings:
    return get_kg_config_settings(db_session=db_session)


@admin_router.post("/configs")
def update_kg_configs(
    update_request: KGConfigSettings,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_kg_config_settings(db_session=db_session, kg_config=update_request)
