from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.file_store.file_store import get_default_file_store
from ee.danswer.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.danswer.server.enterprise_settings.models import EnterpriseSettings
from ee.danswer.server.enterprise_settings.store import _LOGO_FILENAME
from ee.danswer.server.enterprise_settings.store import load_analytics_script
from ee.danswer.server.enterprise_settings.store import load_settings
from ee.danswer.server.enterprise_settings.store import store_analytics_script
from ee.danswer.server.enterprise_settings.store import store_settings
from ee.danswer.server.enterprise_settings.store import upload_logo

admin_router = APIRouter(prefix="/admin/enterprise-settings")
basic_router = APIRouter(prefix="/enterprise-settings")


@admin_router.put("")
def put_settings(
    settings: EnterpriseSettings, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        settings.check_validity()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store_settings(settings)


@basic_router.get("")
def fetch_settings() -> EnterpriseSettings:
    return load_settings()


@admin_router.put("/logo")
def put_logo(
    file: UploadFile,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    upload_logo(file=file, db_session=db_session)


@basic_router.get("/logo")
def fetch_logo(db_session: Session = Depends(get_session)) -> Response:
    try:
        file_store = get_default_file_store(db_session)
        file_io = file_store.read_file(_LOGO_FILENAME, mode="b")
        # NOTE: specifying "image/jpeg" here, but it still works for pngs
        # TODO: do this properly
        return Response(content=file_io.read(), media_type="image/jpeg")
    except Exception:
        raise HTTPException(status_code=404, detail="No logo file found")


@admin_router.put("/custom-analytics-script")
def upload_custom_analytics_script(
    script_upload: AnalyticsScriptUpload, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        store_analytics_script(script_upload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@basic_router.get("/custom-analytics-script")
def fetch_custom_analytics_script() -> str | None:
    return load_analytics_script()
