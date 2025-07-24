from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.exc import IntegrityError

from ee.onyx.auth.users import generate_anonymous_user_jwt_token
from ee.onyx.server.tenants.anonymous_user_path import get_anonymous_user_path
from ee.onyx.server.tenants.anonymous_user_path import (
    get_tenant_id_for_anonymous_user_path,
)
from ee.onyx.server.tenants.anonymous_user_path import modify_anonymous_user_path
from ee.onyx.server.tenants.anonymous_user_path import validate_anonymous_user_path
from ee.onyx.server.tenants.models import AnonymousUserPath
from onyx.auth.users import anonymous_user_enabled
from onyx.auth.users import current_admin_user
from onyx.auth.users import optional_user
from onyx.auth.users import User
from onyx.configs.constants import ANONYMOUS_USER_COOKIE_NAME
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.get("/anonymous-user-path")
async def get_anonymous_user_path_api(
    _: User | None = Depends(current_admin_user),
) -> AnonymousUserPath:
    tenant_id = get_current_tenant_id()

    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    with get_session_with_shared_schema() as db_session:
        current_path = get_anonymous_user_path(tenant_id, db_session)

    return AnonymousUserPath(anonymous_user_path=current_path)


@router.post("/anonymous-user-path")
async def set_anonymous_user_path_api(
    anonymous_user_path: str,
    _: User | None = Depends(current_admin_user),
) -> None:
    tenant_id = get_current_tenant_id()
    try:
        validate_anonymous_user_path(anonymous_user_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with get_session_with_shared_schema() as db_session:
        try:
            modify_anonymous_user_path(tenant_id, anonymous_user_path, db_session)
        except IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="The anonymous user path is already in use. Please choose a different path.",
            )
        except Exception as e:
            logger.exception(f"Failed to modify anonymous user path: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while modifying the anonymous user path",
            )


@router.post("/anonymous-user")
async def login_as_anonymous_user(
    anonymous_user_path: str,
    _: User | None = Depends(optional_user),
) -> Response:
    with get_session_with_shared_schema() as db_session:
        tenant_id = get_tenant_id_for_anonymous_user_path(
            anonymous_user_path, db_session
        )
        if not tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")

    if not anonymous_user_enabled(tenant_id=tenant_id):
        raise HTTPException(status_code=403, detail="Anonymous user is not enabled")

    token = generate_anonymous_user_jwt_token(tenant_id)

    response = Response()
    response.delete_cookie(FASTAPI_USERS_AUTH_COOKIE_NAME)
    response.set_cookie(
        key=ANONYMOUS_USER_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response
