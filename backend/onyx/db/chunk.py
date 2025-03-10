from datetime import datetime
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.models import ChunkStats


def update_chunk_boost_components__no_commit(
    chunk_data: list[dict],
    db_session: Session,
) -> None:
    """Updates the chunk_boost_components for chunks in the database.

    Args:
        chunk_data: List of dicts containing chunk_id, document_id, and boost_score
        db_session: SQLAlchemy database session
    """
    if not chunk_data:
        return

    for data in chunk_data:
        chunk_in_doc_id = str(data.get("chunk_id", ""))
        if len(chunk_in_doc_id) == 0:
            raise ValueError(f"Chunk ID is empty for chunk {data}")
        chunk_stats = (
            db_session.query(ChunkStats)
            .filter(
                ChunkStats.document_id == data["document_id"],
                ChunkStats.chunk_in_doc_id == chunk_in_doc_id,
            )
            .first()
        )

        boost_components = {"information_content_boost": data["boost_score"]}

        if chunk_stats:
            # Update existing record
            if chunk_stats.chunk_boost_components:
                chunk_stats.chunk_boost_components.update(boost_components)
            else:
                chunk_stats.chunk_boost_components = boost_components
            chunk_stats.last_modified = datetime.now(timezone.utc)
        else:
            # Create new record
            chunk_stats = ChunkStats(
                # id=data["chunk_id"],
                document_id=data["document_id"],
                chunk_in_doc_id=chunk_in_doc_id,
                chunk_boost_components=boost_components,
            )
            db_session.add(chunk_stats)


def delete_chunk_stats_by_connector_credential_pair__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """This deletes just chunk stats in postgres."""
    stmt = delete(ChunkStats).where(ChunkStats.document_id.in_(document_ids))

    db_session.execute(stmt)
