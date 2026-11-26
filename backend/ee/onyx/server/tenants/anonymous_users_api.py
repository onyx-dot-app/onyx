from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import IntegrityError

from ee.onyx.auth.users import generate_anonymous_user_jwt_token
from ee.onyx.server.tenants.anonymous_user_path import (
    get_anonymous_user_path,
    get_tenant_id_for_anonymous_user_path,
    modify_anonymous_user_path,
    validate_anonymous_user_path,
)
from ee.onyx.server.tenants.models import AnonymousUserPath
from onyx.auth.permissions import require_permission
from onyx.auth.users import User, anonymous_user_enabled
from onyx.configs.constants import (
    ANONYMOUS_USER_COOKIE_NAME,
    FASTAPI_USERS_AUTH_COOKIE_NAME,
)
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.playground import PlaygroundRestrictedFeature, restrict_in_playground
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.get("/anonymous-user-path")
async def get_anonymous_user_path_api(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> AnonymousUserPath:
    tenant_id = get_current_tenant_id()

    if tenant_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Tenant not found")

    with get_session_with_shared_schema() as db_session:
        current_path = get_anonymous_user_path(tenant_id, db_session)

    return AnonymousUserPath(anonymous_user_path=current_path)


@router.post(
    "/anonymous-user-path",
    dependencies=[
        Depends(restrict_in_playground(PlaygroundRestrictedFeature.ANONYMOUS_ACCESS))
    ],
)
async def set_anonymous_user_path_api(
    anonymous_user_path: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    tenant_id = get_current_tenant_id()
    try:
        validate_anonymous_user_path(anonymous_user_path)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))

    with get_session_with_shared_schema() as db_session:
        try:
            modify_anonymous_user_path(tenant_id, anonymous_user_path, db_session)
        except IntegrityError:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "The anonymous user path is already in use. Please choose a different path.",
            )
        except Exception as e:
            logger.exception("Failed to modify anonymous user path: %s", str(e))
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "An unexpected error occurred while modifying the anonymous user path",
            )


@router.post("/anonymous-user")
async def login_as_anonymous_user(
    anonymous_user_path: str,
) -> Response:
    with get_session_with_shared_schema() as db_session:
        tenant_id = get_tenant_id_for_anonymous_user_path(
            anonymous_user_path, db_session
        )
        if not tenant_id:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Tenant not found")

    if not anonymous_user_enabled(tenant_id=tenant_id):
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Anonymous user is not enabled")

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
