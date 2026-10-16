"""The orphan cleanup deletes API tokens no feature uses, past a grace period,
and leaves tokens in use alone."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.api_token import create_api_token, delete_orphaned_api_tokens
from onyx.db.models import ApiToken, InternetSearchProvider

_PLATFORM = "orphan-cleanup-test"


def _age(db_session: Session, token_id: int, hours: int) -> None:
    db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == token_id)
        .values(time_updated=datetime.now(timezone.utc) - timedelta(hours=hours))
    )
    db_session.commit()


@pytest.fixture
def tokens(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[dict[str, int], None, None]:
    old_orphan = create_api_token(db_session, platform=_PLATFORM, value="sk-old")
    new_orphan = create_api_token(db_session, platform=_PLATFORM, value="sk-new")
    in_use = create_api_token(db_session, platform=_PLATFORM, value="sk-used")
    provider = InternetSearchProvider(
        name=f"orphan-cleanup-{uuid4()}", provider_type=_PLATFORM
    )
    provider.api_token = in_use
    db_session.add(provider)
    db_session.commit()
    for token in (old_orphan, in_use):
        _age(db_session, token.id, hours=2)

    yield {
        "old_orphan": old_orphan.id,
        "new_orphan": new_orphan.id,
        "in_use": in_use.id,
    }

    db_session.delete(provider)
    db_session.commit()
    db_session.query(ApiToken).filter(ApiToken.platform == _PLATFORM).delete()
    db_session.commit()


def test_deletes_only_old_unused_tokens(
    db_session: Session, tokens: dict[str, int]
) -> None:
    # Under test.
    delete_orphaned_api_tokens(
        db_session, unused_since=datetime.now(timezone.utc) - timedelta(hours=1)
    )

    # Postcondition.
    remaining = {
        token_id
        for (token_id,) in db_session.query(ApiToken.id).filter(
            ApiToken.platform == _PLATFORM
        )
    }
    assert tokens["old_orphan"] not in remaining
    assert tokens["new_orphan"] in remaining
    assert tokens["in_use"] in remaining
