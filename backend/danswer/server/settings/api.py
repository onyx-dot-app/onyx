from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.db.models import User
from danswer.server.settings.models import Settings
from danswer.server.settings.store import load_settings
from danswer.server.settings.store import store_settings


admin_router = APIRouter(prefix="/admin/settings")
basic_router = APIRouter(prefix="/settings")


@admin_router.put("")
def put_settings(
    settings: Settings, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        settings.check_validity()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store_settings(settings)


@basic_router.get("")
def fetch_settings(_: User | None = Depends(current_user)) -> Settings:
    return load_settings()
