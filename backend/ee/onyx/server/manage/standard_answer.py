from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import (
    fetch_standard_answer,
    fetch_standard_answer_categories,
    fetch_standard_answer_category,
    fetch_standard_answers,
    insert_standard_answer,
    insert_standard_answer_category,
    remove_standard_answer,
    update_standard_answer,
    update_standard_answer_category,
)
from ee.onyx.server.manage.models import (
    StandardAnswer,
    StandardAnswerCategory,
    StandardAnswerCategoryCreationRequest,
    StandardAnswerCreationRequest,
)
from onyx.auth.users import current_curator_or_admin_user
from onyx.db.engine import get_session
from onyx.db.models import User

router = APIRouter(tags=["Стандартные ответы"])


@router.post(
    "/manage/admin/standard-answer",
    summary="Создание нового стандартного ответа для автоматического реагирования",
    response_model=StandardAnswer,
)
def create_standard_answer(
    standard_answer_creation_request: StandardAnswerCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> StandardAnswer:
    """Создание нового стандартного ответа для автоматического реагирования.

    Стандартные ответы используются для автоматических ответов на сообщения пользователей
    по ключевым словам или regex-паттернам. Поддерживает два режима работы:
    keyword-режим и regex-режим с соответствующей валидацией.

    Args:
        standard_answer_creation_request: Данные для создания стандартного ответа

    Returns:
        Созданный стандартный ответ с присвоенным идентификатором
    """
    standard_answer = insert_standard_answer(
        keyword=standard_answer_creation_request.keyword,
        answer=standard_answer_creation_request.answer,
        category_ids=standard_answer_creation_request.categories,
        match_regex=standard_answer_creation_request.match_regex,
        match_any_keywords=standard_answer_creation_request.match_any_keywords,
        db_session=db_session,
    )

    result_standard_answer = StandardAnswer.from_model(standard_answer)
    return result_standard_answer


@router.get(
    "/manage/admin/standard-answer",
    summary="Получение списка всех активных стандартных ответов",
    response_model=list[StandardAnswer],
)
def list_standard_answers(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> list[StandardAnswer]:
    """Получение списка всех активных стандартных ответов.

    Возвращает стандартные ответы, которые используются для автоматического
    реагирования на сообщения пользователей по ключевым словам или regex-паттернам.

    Returns:
        Список активных стандартных ответов с категориями
    """
    standard_answers = fetch_standard_answers(db_session=db_session)

    result_standard_answers_list: list[StandardAnswer] = []
    for answer_model in standard_answers:
        standard_answer = StandardAnswer.from_model(answer_model)
        result_standard_answers_list.append(standard_answer)

    return result_standard_answers_list


@router.patch(
    "/manage/admin/standard-answer/{standard_answer_id}",
    summary="Частичное обновление существующего стандартного ответа",
    response_model=StandardAnswer,
)
def patch_standard_answer(
    standard_answer_id: int,
    standard_answer_creation_request: StandardAnswerCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> StandardAnswer:
    """Частичное обновление существующего стандартного ответа.

    Позволяет изменить ключевое слово, текст ответа, категории и параметры
    сопоставления. Все поля обязательны для обновления.

    Args:
        standard_answer_id: Идентификатор обновляемого стандартного ответа
        standard_answer_creation_request: Новые данные для стандартного ответа

    Returns:
        Обновленный стандартный ответ
    """
    existing_standard_answer = fetch_standard_answer(
        standard_answer_id=standard_answer_id,
        db_session=db_session,
    )

    if existing_standard_answer is None:
        raise HTTPException(
            status_code=404,
            detail="Стандартный ответ не найден",
        )

    standard_answer_model = update_standard_answer(
        standard_answer_id=standard_answer_id,
        keyword=standard_answer_creation_request.keyword,
        answer=standard_answer_creation_request.answer,
        category_ids=standard_answer_creation_request.categories,
        match_regex=standard_answer_creation_request.match_regex,
        match_any_keywords=standard_answer_creation_request.match_any_keywords,
        db_session=db_session,
    )

    result_standard_answer_model = StandardAnswer.from_model(standard_answer_model)
    return result_standard_answer_model


@router.delete(
    "/manage/admin/standard-answer/{standard_answer_id}",
    summary="Удаление стандартного ответа из системы",
)
def delete_standard_answer(
    standard_answer_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> None:
    """Удаление стандартного ответа из системы.

    Выполняет мягкое удаление (деактивацию) стандартного ответа.
    Ответ больше не будет использоваться для автоматических ответов,
    но сохранится в базе данных.

    Args:
        standard_answer_id: Идентификатор удаляемого стандартного ответа
    """
    remove_standard_answer(
        standard_answer_id=standard_answer_id,
        db_session=db_session,
    )


@router.post(
    "/manage/admin/standard-answer/category",
    summary="Создание категории стандартных ответов",
    response_model=StandardAnswerCategory,
)
def create_standard_answer_category(
    standard_answer_category_creation_request: StandardAnswerCategoryCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> StandardAnswerCategory:
    """Создание категории стандартных ответов.

    Категории используются для организации стандартных ответов по тематикам
    или назначению. Позволяют фильтровать и управлять ответами более эффективно.

    Args:
        standard_answer_category_creation_request: Данные для создания категории

    Returns:
        Созданная категория стандартных ответов с присвоенным идентификатором
    """
    category_model = insert_standard_answer_category(
        category_name=standard_answer_category_creation_request.name,
        db_session=db_session,
    )

    result_category = StandardAnswerCategory.from_model(category_model)
    return result_category


@router.get(
    "/manage/admin/standard-answer/category",
    summary="Получение списка всех категорий стандартных ответов",
    response_model=list[StandardAnswerCategory],
)
def list_standard_answer_categories(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> list[StandardAnswerCategory]:
    """Получение списка всех категорий стандартных ответов.

    Категории используются для организации и группировки стандартных ответов
    по тематикам, что упрощает управление и фильтрацию ответов.

    Returns:
        Список всех категорий стандартных ответов
    """
    category_models = fetch_standard_answer_categories(
        db_session=db_session
    )

    result_categories_list = []
    for category_model in category_models:
        category = StandardAnswerCategory.from_model(category_model)
        result_categories_list.append(category)

    return result_categories_list


@router.patch(
    "/manage/admin/standard-answer/category/{standard_answer_category_id}",
    summary="Обновление названия категории стандартных ответов",
    response_model=StandardAnswerCategory,
)
def patch_standard_answer_category(
    standard_answer_category_id: int,
    standard_answer_category_creation_request: StandardAnswerCategoryCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_curator_or_admin_user),
) -> StandardAnswerCategory:
    """Обновление названия категории стандартных ответов.

    Позволяет изменить название существующей категории для лучшей
    организации и идентификации групп стандартных ответов.

    Args:
        standard_answer_category_id: Идентификатор обновляемой категории
        standard_answer_category_creation_request: Новые данные для категории

    Returns:
        Обновленная категория стандартных ответов
    """
    existing_standard_answer_category = fetch_standard_answer_category(
        standard_answer_category_id=standard_answer_category_id,
        db_session=db_session,
    )

    if existing_standard_answer_category is None:
        raise HTTPException(
            status_code=404,
            detail=f"Категория стандартных ответов id='{standard_answer_category_id}' не найдена",
        )

    updated_category_model = update_standard_answer_category(
        standard_answer_category_id=standard_answer_category_id,
        category_name=standard_answer_category_creation_request.name,
        db_session=db_session,
    )

    result_category = StandardAnswerCategory.from_model(updated_category_model)
    return result_category
