from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Sandbox


def any_sandbox_exists(db_session: Session) -> bool:
    """Whether this tenant has a sandbox row in any status."""
    return db_session.scalar(select(Sandbox.id).limit(1)) is not None
