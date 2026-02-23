from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import CodeInterpreterServer


def insert_code_interpreter_server(
    db_session: Session,
    url: str,
    server_enabled: bool,
) -> CodeInterpreterServer:
    code_interpreter_server = CodeInterpreterServer(
        url=url, server_enabled=server_enabled
    )

    db_session.add(code_interpreter_server)
    db_session.commit()
    return code_interpreter_server


def fetch_code_interpreter_servers(
    db_session: Session,
) -> list[CodeInterpreterServer]:
    return list(db_session.scalars(select(CodeInterpreterServer)).all())
