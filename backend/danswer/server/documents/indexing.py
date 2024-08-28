from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from danswer.db.index_attempt import (
    get_index_attempt_errors,
)
from danswer.db.models import User
from danswer.server.documents.models import IndexAttemptError

router = APIRouter(prefix="/manage")


@router.get("/admin/indexing-errors/{index_attempt_id}")
def get_indexing_errors(
    index_attempt_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[IndexAttemptError]:
    indexing_errors = get_index_attempt_errors(index_attempt_id, db_session)
    return [IndexAttemptError.from_db_model(e) for e in indexing_errors]
