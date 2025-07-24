from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import fetch_standard_answer
from ee.onyx.db.standard_answer import fetch_standard_answer_categories
from ee.onyx.db.standard_answer import fetch_standard_answer_category
from ee.onyx.db.standard_answer import fetch_standard_answers
from ee.onyx.db.standard_answer import insert_standard_answer
from ee.onyx.db.standard_answer import insert_standard_answer_category
from ee.onyx.db.standard_answer import remove_standard_answer
from ee.onyx.db.standard_answer import update_standard_answer
from ee.onyx.db.standard_answer import update_standard_answer_category
from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.manage.models import StandardAnswer
from onyx.server.manage.models import StandardAnswerCategory
from onyx.server.manage.models import StandardAnswerCategoryCreationRequest
from onyx.server.manage.models import StandardAnswerCreationRequest

router = APIRouter(prefix="/manage")


@router.post("/admin/standard-answer")
def create_standard_answer(
    standard_answer_creation_request: StandardAnswerCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> StandardAnswer:
    standard_answer_model = insert_standard_answer(
        keyword=standard_answer_creation_request.keyword,
        answer=standard_answer_creation_request.answer,
        category_ids=standard_answer_creation_request.categories,
        match_regex=standard_answer_creation_request.match_regex,
        match_any_keywords=standard_answer_creation_request.match_any_keywords,
        db_session=db_session,
    )
    return StandardAnswer.from_model(standard_answer_model)


@router.get("/admin/standard-answer")
def list_standard_answers(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[StandardAnswer]:
    standard_answer_models = fetch_standard_answers(db_session=db_session)
    return [
        StandardAnswer.from_model(standard_answer_model)
        for standard_answer_model in standard_answer_models
    ]


@router.patch("/admin/standard-answer/{standard_answer_id}")
def patch_standard_answer(
    standard_answer_id: int,
    standard_answer_creation_request: StandardAnswerCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> StandardAnswer:
    existing_standard_answer = fetch_standard_answer(
        standard_answer_id=standard_answer_id,
        db_session=db_session,
    )

    if existing_standard_answer is None:
        raise HTTPException(status_code=404, detail="Standard answer not found")

    standard_answer_model = update_standard_answer(
        standard_answer_id=standard_answer_id,
        keyword=standard_answer_creation_request.keyword,
        answer=standard_answer_creation_request.answer,
        category_ids=standard_answer_creation_request.categories,
        match_regex=standard_answer_creation_request.match_regex,
        match_any_keywords=standard_answer_creation_request.match_any_keywords,
        db_session=db_session,
    )
    return StandardAnswer.from_model(standard_answer_model)


@router.delete("/admin/standard-answer/{standard_answer_id}")
def delete_standard_answer(
    standard_answer_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    return remove_standard_answer(
        standard_answer_id=standard_answer_id,
        db_session=db_session,
    )


@router.post("/admin/standard-answer/category")
def create_standard_answer_category(
    standard_answer_category_creation_request: StandardAnswerCategoryCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> StandardAnswerCategory:
    standard_answer_category_model = insert_standard_answer_category(
        category_name=standard_answer_category_creation_request.name,
        db_session=db_session,
    )
    return StandardAnswerCategory.from_model(standard_answer_category_model)


@router.get("/admin/standard-answer/category")
def list_standard_answer_categories(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[StandardAnswerCategory]:
    standard_answer_category_models = fetch_standard_answer_categories(
        db_session=db_session
    )
    return [
        StandardAnswerCategory.from_model(standard_answer_category_model)
        for standard_answer_category_model in standard_answer_category_models
    ]


@router.patch("/admin/standard-answer/category/{standard_answer_category_id}")
def patch_standard_answer_category(
    standard_answer_category_id: int,
    standard_answer_category_creation_request: StandardAnswerCategoryCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> StandardAnswerCategory:
    existing_standard_answer_category = fetch_standard_answer_category(
        standard_answer_category_id=standard_answer_category_id,
        db_session=db_session,
    )

    if existing_standard_answer_category is None:
        raise HTTPException(
            status_code=404, detail="Standard answer category not found"
        )

    standard_answer_category_model = update_standard_answer_category(
        standard_answer_category_id=standard_answer_category_id,
        category_name=standard_answer_category_creation_request.name,
        db_session=db_session,
    )
    return StandardAnswerCategory.from_model(standard_answer_category_model)
