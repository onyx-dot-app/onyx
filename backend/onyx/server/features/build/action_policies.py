"""The Craft policy catalog: the plugins the user runs in Craft, with the
effective policy of each integration action for the user."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.integrations.craft import TaskPluginView, list_task_plugin_views

router = APIRouter(prefix="/action-policies")


@router.get("")
def list_personal_action_policies(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TaskPluginView]:
    """Each action inherits; the effective policy includes the user's saved
    Always allow. A new task starts from this catalog."""
    return list_task_plugin_views(db_session, user, None)
