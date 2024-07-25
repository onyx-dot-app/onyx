from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.models import Document


def fetch_documents_from_ids(
    db_session: Session, document_ids: list[str]
) -> Sequence[Document]:
    return db_session.scalars(
        select(Document).where(Document.id.in_(document_ids))
    ).all()
