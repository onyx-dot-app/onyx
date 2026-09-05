"""Deleting a standard answer category.

Categories are many-to-many with standard answers and with Slack channel
configs, so what blocks a delete — and what is cleaned up instead — needs to be
pinned down rather than inferred from ORM behaviour.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import (
    fetch_standard_answer_category,
    insert_standard_answer,
    insert_standard_answer_category,
    remove_standard_answer,
    remove_standard_answer_category,
)
from onyx.db.models import StandardAnswer__StandardAnswerCategory
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _category(db_session: Session) -> int:
    return insert_standard_answer_category(
        category_name=f"cat-{uuid4().hex[:8]}", db_session=db_session
    ).id


def _answer(db_session: Session, category_id: int) -> int:
    return insert_standard_answer(
        keyword=f"kw-{uuid4().hex[:8]}",
        answer="an answer",
        category_ids=[category_id],
        match_regex=False,
        match_any_keywords=False,
        db_session=db_session,
    ).id


def test_an_unreferenced_category_is_deleted(db_session: Session) -> None:
    category_id = _category(db_session)

    remove_standard_answer_category(
        standard_answer_category_id=category_id, db_session=db_session
    )

    assert (
        fetch_standard_answer_category(
            standard_answer_category_id=category_id, db_session=db_session
        )
        is None
    )


def test_an_active_standard_answer_blocks_the_delete(db_session: Session) -> None:
    category_id = _category(db_session)
    _answer(db_session, category_id)

    with pytest.raises(OnyxError) as exc_info:
        remove_standard_answer_category(
            standard_answer_category_id=category_id, db_session=db_session
        )

    assert exc_info.value.error_code is OnyxErrorCode.RESOURCE_IN_USE
    assert (
        fetch_standard_answer_category(
            standard_answer_category_id=category_id, db_session=db_session
        )
        is not None
    )


def test_a_deactivated_standard_answer_does_not_block_the_delete(
    db_session: Session,
) -> None:
    """The association rows survive deactivation, so this is the case that would
    fail with a foreign key error if they were not cleaned up with the category."""
    category_id = _category(db_session)
    answer_id = _answer(db_session, category_id)
    remove_standard_answer(standard_answer_id=answer_id, db_session=db_session)

    remove_standard_answer_category(
        standard_answer_category_id=category_id, db_session=db_session
    )

    assert (
        fetch_standard_answer_category(
            standard_answer_category_id=category_id, db_session=db_session
        )
        is None
    )
    # The link went with the category rather than being left dangling.
    remaining = db_session.scalars(
        select(StandardAnswer__StandardAnswerCategory).where(
            StandardAnswer__StandardAnswerCategory.standard_answer_category_id
            == category_id
        )
    ).all()
    assert remaining == []


def test_a_missing_category_is_not_found(db_session: Session) -> None:
    with pytest.raises(OnyxError) as exc_info:
        remove_standard_answer_category(
            standard_answer_category_id=2_000_000_000, db_session=db_session
        )

    assert exc_info.value.error_code is OnyxErrorCode.NOT_FOUND
