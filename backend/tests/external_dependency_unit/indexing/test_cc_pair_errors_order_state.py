"""The pair's errors in state order: open rows first, then rows resolved
without retry, then rows a run, a Retry or a legacy resolve closed, each
group newest first, held across page boundaries."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IndexAttemptErrorOrder,
    IndexAttemptErrorResolvedReason,
    IndexingStatus,
)
from onyx.db.models import ConnectorCredentialPair, IndexAttemptError, User
from onyx.server.documents.cc_pair import get_cc_pair_indexing_errors
from tests.external_dependency_unit.indexing.test_cc_pair_errors_resolve_route import (
    _attempt,
    _error,
    _resolve_errors,
    admin,  # noqa: F401
    pairs,  # noqa: F401
)

# The shared pair fixture's cleanup reads EE-only run kinds.
pytestmark = pytest.mark.usefixtures("enable_ee")

_Pairs = tuple[ConnectorCredentialPair, ConnectorCredentialPair]


def _close(
    db_session: Session,
    error_id: int,
    reason: IndexAttemptErrorResolvedReason | None,
) -> None:
    db_session.execute(
        update(IndexAttemptError)
        .where(IndexAttemptError.id == error_id)
        .values(is_resolved=True, resolved_reason=reason)
    )
    db_session.commit()


def _all_pages(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    order: IndexAttemptErrorOrder,
) -> list[int]:
    ids: list[int] = []
    page_num = 0
    while True:
        page = get_cc_pair_indexing_errors(
            cc_pair_id=pair.id,
            include_resolved=True,
            page_num=page_num,
            page_size=2,
            index_attempt_id=None,
            q=None,
            order=order,
            user=user,
            db_session=db_session,
        )
        ids.extend(error.id for error in page.items)
        if not page.items:
            return ids
        page_num += 1


def test_state_order_groups_open_then_without_retry_then_closed_across_pages(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    now = datetime.now(timezone.utc)

    def error(document_id: str, minutes_ago: int) -> int:
        return _error(
            db_session,
            attempt,
            document_id,
            created=now - timedelta(minutes=minutes_ago),
        )

    # Created times interleave the groups, so a time order mixes them.
    retried = error("retried", 1)
    without_retry_new = error("without-retry-new", 2)
    open_new = error("open-new", 3)
    legacy = error("legacy", 4)
    without_retry_old = error("without-retry-old", 5)
    later_run = error("later-run", 6)
    open_old = error("open-old", 7)
    assert (
        _resolve_errors(db_session, admin, pair, [without_retry_new, without_retry_old])
        == 2
    )
    _close(db_session, retried, IndexAttemptErrorResolvedReason.RETRY)
    _close(db_session, later_run, IndexAttemptErrorResolvedReason.LATER_RUN)
    _close(db_session, legacy, None)

    assert _all_pages(db_session, admin, pair, IndexAttemptErrorOrder.STATE) == [
        open_new,
        open_old,
        without_retry_new,
        without_retry_old,
        retried,
        legacy,
        later_run,
    ]
    assert _all_pages(db_session, admin, pair, IndexAttemptErrorOrder.TIME) == [
        retried,
        without_retry_new,
        open_new,
        legacy,
        without_retry_old,
        later_run,
        open_old,
    ]
