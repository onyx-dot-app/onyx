import re
import string
from collections.abc import Sequence
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import StandardAnswer
from onyx.db.models import StandardAnswerCategory
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _validate_category_length(name: str) -> bool:
    """Проверяет длину имени категории для соответствия ограничениям БД."""
    if len(name) > 255:
        logger.error(f"Имя категории '{name}' превышает допустимую длину")
        return False
    return True


def insert_standard_answer_category(
    category_name: str, db_session: Session
) -> StandardAnswerCategory:
    if not _validate_category_length(category_name):
        raise ValueError(f"Недопустимое имя категории: {category_name}")
    new_category = StandardAnswerCategory(name=category_name)
    db_session.add(new_category)
    db_session.commit()
    return new_category


def _retrieve_categories_by_ids(
    cat_ids: List[int], session: Session
) -> List[StandardAnswerCategory]:
    """Извлекает категории по списку ID."""
    query = select(StandardAnswerCategory).where(
        StandardAnswerCategory.id.in_(cat_ids)
    )
    return session.scalars(query).all()


def insert_standard_answer(
    keyword: str,
    answer: str,
    category_ids: list[int],
    match_regex: bool,
    match_any_keywords: bool,
    db_session: Session,
) -> StandardAnswer:
    retrieved_cats = _retrieve_categories_by_ids(category_ids, db_session)
    if len(retrieved_cats) != len(category_ids):
        raise ValueError(f"Не все категории с ID {category_ids} существуют")

    new_answer = StandardAnswer(
        keyword=keyword,
        answer=answer,
        categories=retrieved_cats,
        active=True,
        match_regex=match_regex,
        match_any_keywords=match_any_keywords,
    )
    db_session.add(new_answer)
    db_session.commit()
    return new_answer


def update_standard_answer(
    standard_answer_id: int,
    keyword: str,
    answer: str,
    category_ids: list[int],
    match_regex: bool,
    match_any_keywords: bool,
    db_session: Session,
) -> StandardAnswer:
    query = select(StandardAnswer).where(StandardAnswer.id == standard_answer_id)
    target_answer = db_session.scalar(query)
    if target_answer is None:
        raise ValueError(f"Стандартный ответ с ID {standard_answer_id} не найден")

    retrieved_cats = _retrieve_categories_by_ids(category_ids, db_session)
    if len(retrieved_cats) != len(category_ids):
        raise ValueError(f"Не все категории с ID {category_ids} существуют")

    target_answer.keyword = keyword
    target_answer.answer = answer
    target_answer.categories = retrieved_cats
    target_answer.match_regex = match_regex
    target_answer.match_any_keywords = match_any_keywords

    db_session.commit()
    return target_answer


def remove_standard_answer(
    standard_answer_id: int,
    db_session: Session,
) -> None:
    query = select(StandardAnswer).where(StandardAnswer.id == standard_answer_id)
    target_answer = db_session.scalar(query)
    if target_answer is None:
        raise ValueError(f"Стандартный ответ с ID {standard_answer_id} не найден")

    target_answer.active = False
    db_session.commit()


def update_standard_answer_category(
    standard_answer_category_id: int,
    category_name: str,
    db_session: Session,
) -> StandardAnswerCategory:
    query = select(StandardAnswerCategory).where(
        StandardAnswerCategory.id == standard_answer_category_id
    )
    target_category = db_session.scalar(query)
    if target_category is None:
        raise ValueError(
            f"Категория стандартных ответов с ID {standard_answer_category_id} не найдена"
        )

    if not _validate_category_length(category_name):
        raise ValueError(f"Недопустимое имя категории: {category_name}")

    target_category.name = category_name
    db_session.commit()
    return target_category


def fetch_standard_answer_category(
    standard_answer_category_id: int,
    db_session: Session,
) -> StandardAnswerCategory | None:
    query = select(StandardAnswerCategory).where(
        StandardAnswerCategory.id == standard_answer_category_id
    )
    return db_session.scalar(query)


def fetch_standard_answer_categories_by_ids(
    standard_answer_category_ids: list[int],
    db_session: Session,
) -> Sequence[StandardAnswerCategory]:
    return _retrieve_categories_by_ids(standard_answer_category_ids, db_session)


def fetch_standard_answer_categories(
    db_session: Session,
) -> Sequence[StandardAnswerCategory]:
    query = select(StandardAnswerCategory)
    return db_session.scalars(query).all()


def fetch_standard_answer(
    standard_answer_id: int,
    db_session: Session,
) -> StandardAnswer | None:
    query = select(StandardAnswer).where(StandardAnswer.id == standard_answer_id)
    return db_session.scalar(query)


def fetch_standard_answers(db_session: Session) -> Sequence[StandardAnswer]:
    query = select(StandardAnswer).where(StandardAnswer.active.is_(True))
    return db_session.scalars(query).all()


def _ensure_default_category(session: Session, default_name: str) -> None:
    """Обеспечивает наличие дефолтной категории с заданным именем."""
    default_id = 0
    existing_cat = fetch_standard_answer_category(default_id, session)
    if existing_cat:
        if existing_cat.name != default_name:
            raise ValueError(
                "База данных в некорректном начальном состоянии. "
                "Дефолтная категория имеет неожиданное имя."
            )
        return

    new_default = StandardAnswerCategory(id=default_id, name=default_name)
    session.add(new_default)
    session.commit()


def create_initial_default_standard_answer_category(db_session: Session) -> None:
    _ensure_default_category(db_session, "General")


def fetch_standard_answer_categories_by_names(
    standard_answer_category_names: list[str],
    db_session: Session,
) -> Sequence[StandardAnswerCategory]:
    query = select(StandardAnswerCategory).where(
        StandardAnswerCategory.name.in_(standard_answer_category_names)
    )
    return db_session.scalars(query).all()


def _normalize_text(text: str) -> set[str]:
    """Удаляет пунктуацию и разбивает текст на слова в нижнем регистре."""
    cleaned = "".join(char for char in text.lower() if char not in string.punctuation)
    return set(cleaned.split())


def _match_regex_pattern(pattern: str, text: str) -> str | None:
    """Проверяет совпадение по regex и возвращает группу совпадения."""
    match_obj = re.search(pattern, text, re.IGNORECASE)
    return match_obj.group(0) if match_obj else None


def _match_keyword_set(
    keyword_set: set[str], query_set: List[str], any_match: bool
) -> str | None:
    """Проверяет наличие ключевых слов в запросе."""
    if any_match:
        for q_word in query_set:
            if q_word in keyword_set:
                return q_word
        return None
    if all(word in query_set for word in keyword_set):
        return ", ".join(keyword_set)
    return None


def find_matching_standard_answers(
    id_in: list[int],
    query: str,
    db_session: Session,
) -> list[tuple[StandardAnswer, str]]:
    """
    Находит стандартные ответы, соответствующие запросу.
    Возвращает пары (ответ, описание совпадения).
    Логика: regex или ключевые слова (все/любое).
    """
    base_query = (
        select(StandardAnswer)
        .where(StandardAnswer.active.is_(True))
        .where(StandardAnswer.id.in_(id_in))
    )
    candidates: Sequence[StandardAnswer] = db_session.scalars(base_query).all()

    results: List[Tuple[StandardAnswer, str]] = []
    query_words = "".join(
        char for char in query.lower() if char not in string.punctuation
    ).split()

    idx = 0
    while idx < len(candidates):
        candidate = candidates[idx]
        match_desc = None

        if candidate.match_regex:
            match_desc = _match_regex_pattern(candidate.keyword, query)
        else:
            kw_words = _normalize_text(candidate.keyword)
            match_desc = _match_keyword_set(
                kw_words, query_words, candidate.match_any_keywords
            )

        if match_desc:
            results.append((candidate, match_desc))

        idx += 1

    return results
