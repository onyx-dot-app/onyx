from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.build.approvals.api import router as approvals_router
from onyx.server.features.build.debug import router as debug_router
from onyx.server.features.build.external_apps.api import router as external_apps_router
from onyx.server.features.build.external_apps.oauth import (
    router as external_apps_oauth_router,
)
from onyx.server.features.build.interactive_turns.api import router as turns_router
from onyx.server.features.build.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.rate_limit import RateLimitResponse
from onyx.server.features.build.scheduled_tasks.api import (
    router as scheduled_tasks_router,
)
from onyx.server.features.build.session.api import router as sessions_router
from onyx.server.features.build.session.messages import router as messages_router
from onyx.server.features.build.user_library.api import router as user_library_router
from onyx.server.features.build.utils import is_onyx_craft_enabled
from onyx.utils.logger import setup_logger

logger = setup_logger()


def require_onyx_craft_enabled(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> User:
    if not is_onyx_craft_enabled(user):
        raise HTTPException(
            status_code=403,
            detail="Onyx Craft is not available",
        )
    return user


router = APIRouter(prefix="/build", dependencies=[Depends(require_onyx_craft_enabled)])

router.include_router(sessions_router, tags=["build"])
router.include_router(messages_router, tags=["build"])
router.include_router(turns_router, tags=["build"])
router.include_router(user_library_router, tags=["build"])
router.include_router(scheduled_tasks_router, tags=["build"])
router.include_router(external_apps_router, tags=["build"])
router.include_router(external_apps_oauth_router, tags=["build"])
router.include_router(debug_router, tags=["build-debug"])
router.include_router(approvals_router, tags=["build"])


# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------


@router.get("/limit", response_model=RateLimitResponse)
def get_rate_limit(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RateLimitResponse:
    """Get rate limit information for the current user."""
    return get_user_rate_limit_status(user, db_session)
