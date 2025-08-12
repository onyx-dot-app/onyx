from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user, current_user
from onyx.db.engine import get_session
from onyx.db.knowledge_map import insert_knowledge_map, get_knowledge_map_list, delete_knowledge_map_by_id, \
    get_knowledge_map_by_id, update_knowledge_map, get_answers_by_knowledge_map_id
from onyx.db.models import User
from onyx.server.features.knowledge_map.models import CreateKnowledgeMapRequest, KnowledgeMap, \
    EditKnowledgeMapRequest, KnowledgeMapAnswer
from onyx.utils.knowledge_map import get_knowledge_map_answers_by_document_list

router = APIRouter(prefix="/knowledge")


@router.post("/")
async def create_knowledge_map(
        knowledge_map_creation_request: CreateKnowledgeMapRequest,
        _: User = Depends(current_admin_user),
        db_session: Session = Depends(get_session)
) -> int:
    try:
        knowledge_map_db_model = insert_knowledge_map(db_session, knowledge_map_creation_request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return knowledge_map_db_model.id


@router.patch("/")
async def patch_knowledge_map(
        knowledge_map_update_request: EditKnowledgeMapRequest,
        _: User = Depends(current_admin_user),
        db_session: Session = Depends(get_session)
):
    try:
        updated_knowledge_map = update_knowledge_map(knowledge_map_update_request, db_session)
        return updated_knowledge_map
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
async def get_all_knowledge_maps(
        _: User | None = Depends(current_admin_user),
        db_session: Session = Depends(get_session),
) -> list[KnowledgeMap]:
    knowledge_maps: list[KnowledgeMap] = []
    for ds in get_knowledge_map_list(db_session):
        answers = get_answers_by_knowledge_map_id(db_session, ds.id)
        knowledge_maps.append(KnowledgeMap.from_model(ds, answers))
    return knowledge_maps

@router.get("/answers")
async def get_knowledge_map_answers(
        knowledge_map_id: int,
        _: User | None = Depends(current_user),
        db_session: Session = Depends(get_session)
):
    answers = get_answers_by_knowledge_map_id(db_session, knowledge_map_id)

    return {"answers": [KnowledgeMapAnswer.from_model(answer) for answer in answers]}


@router.delete("/")
async def delete_knowledge_map(
        knowledge_map_id: int,
        _: User = Depends(current_admin_user),
        db_session: Session = Depends(get_session),
) -> None:
    try:
        delete_knowledge_map_by_id(db_session, knowledge_map_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/answers")
async def generate_topics_and_answers(
        knowledge_map_id: int,
        _: User = Depends(current_admin_user),
        db_session: Session = Depends(get_session)
):
    knowledge_map_db = get_knowledge_map_by_id(db_session, knowledge_map_id)
    if not knowledge_map_db:
        raise HTTPException(status_code=404, detail=f"Not found knowledge map with id {knowledge_map_id}")

    answers = get_knowledge_map_answers_by_document_list(db_session, knowledge_map_db)

    return answers
