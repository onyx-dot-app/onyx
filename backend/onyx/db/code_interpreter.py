from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import CodeInterpreterServer


def update_code_interpreter_server_enabled(
    db_session: Session,
    enabled: bool,
) -> CodeInterpreterServer:
    server = db_session.scalars(select(CodeInterpreterServer)).one()
    server.server_enabled = enabled
    db_session.commit()
    return server
