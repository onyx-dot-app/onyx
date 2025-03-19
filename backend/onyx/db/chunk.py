from datetime import datetime
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.models import ChunkStats
from onyx.indexing.models import UpdatableChunkData


def update_chunk_boost_components__no_commit(
    chunk_data: list[UpdatableChunkData],
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
        chunk_in_doc_id = int(data.chunk_id)
        if chunk_in_doc_id < 0:
            raise ValueError(f"Chunk ID is empty for chunk {data}")

        chunk_document_id = f"{data.document_id}" f"__{chunk_in_doc_id}"
        chunk_stats = (
            db_session.query(ChunkStats)
            .filter(
                ChunkStats.id == chunk_document_id,
            )
            .first()
        )

        score = data.boost_score

        if chunk_stats:
            chunk_stats.information_content_boost = score
            chunk_stats.last_modified = datetime.now(timezone.utc)
            db_session.add(chunk_stats)
        else:
            # do not save new chunks with a neutral boost score
            if score == 1.0:
                continue
            # Create new record
            chunk_stats = ChunkStats(
                document_id=data.document_id,
                chunk_in_doc_id=chunk_in_doc_id,
                information_content_boost=score,
            )
            db_session.add(chunk_stats)


def delete_chunk_stats_by_connector_credential_pair__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    """This deletes just chunk stats in postgres."""
    stmt = delete(ChunkStats).where(ChunkStats.document_id.in_(document_ids))

    db_session.execute(stmt)
