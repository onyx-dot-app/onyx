from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.code_interpreter import fetch_code_interpreter_server
from onyx.db.code_interpreter import update_code_interpreter_server_enabled
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.manage.code_interpreter.models import CodeInterpreterServer
from onyx.server.manage.code_interpreter.models import CodeInterpreterServerHealth
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)

admin_router = APIRouter(prefix="/admin/code-interpreter")


@admin_router.get("/health")
def get_code_interpreter_health(
    _: User = Depends(current_admin_user),
) -> CodeInterpreterServerHealth:
    try:
        client = CodeInterpreterClient()
        return CodeInterpreterServerHealth(healthy=client.health())
    except ValueError:
        return CodeInterpreterServerHealth(healthy=False)


@admin_router.get("")
def get_code_interpreter(
    _: User = Depends(current_admin_user), db_session: Session = Depends(get_session)
) -> CodeInterpreterServer:
    ci_server = fetch_code_interpreter_server(db_session)
    return CodeInterpreterServer(enabled=ci_server.server_enabled)


@admin_router.put("")
def update_code_interpreter(
    update: CodeInterpreterServer,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_code_interpreter_server_enabled(
        db_session=db_session,
        enabled=update.enabled,
    )
