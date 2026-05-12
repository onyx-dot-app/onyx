"""API endpoints for External Apps (admin management + per-user credentials).

Admin routes (POST/GET/DELETE /admin/apps) manage the org-wide app catalog
and shared organization-level credentials. User routes (/apps, /apps/{id}/
credentials) let an individual user view available apps and store their
per-user credentials for apps they want to use.

All handlers are currently stubs.
"""

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.server.features.build.api.models import UpsertUserCredentialsRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter()


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.post("/admin/apps")
def upsert_external_app(
    request: UpsertExternalAppRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create a new external app, or update an existing one if `id` is set."""
    raise OnyxError(
        OnyxErrorCode.NOT_IMPLEMENTED, "upsert_external_app not implemented"
    )


@router.get("/admin/apps")
def list_external_apps_admin(
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppAdminResponse]:
    """List all external apps with admin-only fields (org credentials, auth template)."""
    raise OnyxError(
        OnyxErrorCode.NOT_IMPLEMENTED, "list_external_apps_admin not implemented"
    )


@router.delete("/admin/apps/{external_app_id}")
def delete_external_app(
    external_app_id: int,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an external app. Cascades to all user-credential rows for the app."""
    raise OnyxError(
        OnyxErrorCode.NOT_IMPLEMENTED, "delete_external_app not implemented"
    )


# =============================================================================
# User Endpoints
# =============================================================================


@router.post("/apps/{external_app_id}/credentials")
def upsert_user_credentials(
    external_app_id: int,
    request: UpsertUserCredentialsRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Set or replace the calling user's credentials for the given external app."""
    raise OnyxError(
        OnyxErrorCode.NOT_IMPLEMENTED, "upsert_user_credentials not implemented"
    )


@router.get("/apps")
def list_external_apps(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppUserResponse]:
    """List all external apps from the user's perspective.

    Each entry is flagged `is_configured` based on whether the calling user
    has credentials stored for it.
    """
    raise OnyxError(OnyxErrorCode.NOT_IMPLEMENTED, "list_external_apps not implemented")
