from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.models import KnowledgeMap, KnowledgeMapAnswer
from onyx.server.features.knowledge_map.models import CreateKnowledgeMapRequest, EditKnowledgeMapRequest


def get_answers_by_topic(
        db_session: Session, topic: str, limit: int | None = None
) -> Sequence[KnowledgeMapAnswer]:
    stmt = select(KnowledgeMapAnswer).where(KnowledgeMapAnswer.topic == topic)

    if limit:
        stmt = stmt.limit(limit)

    return db_session.scalars(stmt).all()


def get_answers_by_document_id(
        db_session: Session, document_id: int, limit: int | None = None
) -> Sequence[KnowledgeMapAnswer]:
    stmt = select(KnowledgeMapAnswer).where(KnowledgeMapAnswer.document_id == document_id)

    if limit:
        stmt = stmt.limit(limit)

    return db_session.scalars(stmt).all()


def get_answers_by_knowledge_map_id(
        db_session: Session, knowledge_map_id: int, limit: int | None = None
) -> Sequence[KnowledgeMapAnswer]:
    stmt = select(KnowledgeMapAnswer).where(KnowledgeMapAnswer.knowledge_map_id == knowledge_map_id)

    if limit:
        stmt = stmt.limit(limit)

    return db_session.scalars(stmt).all()


def get_knowledge_map_list(db_session: Session, limit: int | None = None) -> Sequence[KnowledgeMap]:
    stmt = select(KnowledgeMap)

    if limit:
        stmt = stmt.limit(limit)

    return db_session.scalars(stmt).all()


def get_knowledge_map_by_id(db_session: Session, knowledge_map_id: int) -> KnowledgeMap | None:
    stmt = select(KnowledgeMap).where(KnowledgeMap.id == knowledge_map_id)

    return db_session.scalars(stmt).first()


def upsert_knowledge_map_answer(
        db_session: Session, document_id: str, knowledge_map_id: int, topic: str, answer: str
) -> None:
    insert_stmt = insert(KnowledgeMapAnswer).values(
        document_id=document_id,
        knowledge_map_id=knowledge_map_id,
        topic=topic,
        answer=answer
    )
    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
    db_session.execute(on_conflict_stmt)
    db_session.commit()


def update_knowledge_map(
        knowledge_map_update_request: EditKnowledgeMapRequest, db_session: Session,
) -> KnowledgeMap:
    db_session.begin()

    try:
        knowledge_map = get_knowledge_map_by_id(db_session, knowledge_map_update_request.id)
        if knowledge_map is None:
            raise ValueError(
                f"No knowledge map with ID '{knowledge_map_update_request.id}'"
            )

        knowledge_map.description = knowledge_map_update_request.description
        knowledge_map.document_set_id = knowledge_map_update_request.document_set_id
        knowledge_map.name = knowledge_map_update_request.name
        knowledge_map.flowise_pipeline_id = knowledge_map_update_request.flowise_pipeline_id

        db_session.commit()
    except:
        db_session.rollback()
        raise
    return knowledge_map


def insert_knowledge_map(
        db_session: Session,
        knowledge_map_creation_request: CreateKnowledgeMapRequest,
) -> KnowledgeMap:
    try:
        new_knowledge_map = KnowledgeMap(
            name=knowledge_map_creation_request.name,
            document_set_id=knowledge_map_creation_request.document_set_id,
            description=knowledge_map_creation_request.description,
            flowise_pipeline_id=knowledge_map_creation_request.flowise_pipeline_id
        )
        db_session.add(new_knowledge_map)
        db_session.flush()
        db_session.commit()
    except:
        db_session.rollback()
        raise
    return new_knowledge_map


def delete_knowledge_map_by_id(db_session: Session,
                               knowledge_map_id: int) -> None:
    stmt = delete(KnowledgeMap).where(KnowledgeMap.id == knowledge_map_id)

    db_session.execute(stmt)
    db_session.commit()


def delete_knowledge_map_answer_by_id(db_session: Session,
                                      knowledge_map_answer_id: int) -> None:
    stmt = delete(KnowledgeMapAnswer).where(KnowledgeMapAnswer.id == knowledge_map_answer_id)

    db_session.execute(stmt)
    db_session.commit()


def delete_knowledge_map_answer_by_document_id(db_session: Session,
                                               document_id: int) -> None:
    stmt = delete(KnowledgeMapAnswer).where(KnowledgeMapAnswer.document_id == document_id)

    db_session.execute(stmt)
    db_session.commit()
