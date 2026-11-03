"""External dependency unit tests for the indexing beat under the reindex hold.

While a port-flow reindex finalizes (every seeded connector's port is SUCCESS),
`should_index` starts no PRESENT attempt (a manual trigger stays pending), a
waiting PRESENT attempt is not dispatched, and a port-flow FUTURE starts only the
catch-up polls the hold asks for. A connector FUTURE gave up on is reported to
admins once per reindex.
"""

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing import tasks as docprocessing_tasks
from onyx.background.celery.tasks.docprocessing.tasks import (
    _alert_abandoned_catch_up,
    _dispatch_pair_waiting_attempt,
)
from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.configs.constants import NotificationType
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingMode
from onyx.db.index_attempt import create_index_attempt
from onyx.db.models import ConnectorCredentialPair, Notification, SearchSettings, User
from onyx.db.reindex_hold import PairCatchUpState, ReindexHoldState
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair_and_future,
    make_cc_pair,
    make_future_search_settings,
)


@pytest.fixture
def pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, SearchSettings], None, None]:
    pair = make_cc_pair(db_session)
    future = make_future_search_settings(db_session, use_port_flow=True)
    try:
        yield pair, future
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future.id)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "reindex_hold_admin", is_admin=True)
    yield user
    db_session.rollback()
    db_session.query(Notification).filter(Notification.user_id == user.id).delete(
        synchronize_session="fetch"
    )
    delete_test_user(db_session, user)
    db_session.commit()


def _pair_state(
    db_session: Session, cc_pair_id: int, **overrides: object
) -> PairCatchUpState:
    """A pair that needs catch-up and is due for it, unless overridden."""
    now = get_db_current_time(db_session)
    fields: dict[str, object] = {
        "cc_pair_id": cc_pair_id,
        "active": True,
        "push_based": False,
        "since": now - timedelta(hours=2),
        "present_active": False,
        "future_active": False,
        "last_present_end": now - timedelta(minutes=30),
        "port_completed_at": now - timedelta(hours=1),
        "future_covered_through": None,
        "future_last_success_end": None,
        "future_failed_streak": 0,
        "retry_after": None,
        "now": now,
    }
    fields.update(overrides)
    return PairCatchUpState.model_validate(fields)


def _hold(future: SearchSettings, *pairs: PairCatchUpState) -> ReindexHoldState:
    return ReindexHoldState(
        future_id=future.id,
        finalizing=True,
        pairs={pair.cc_pair_id: pair for pair in pairs},
    )


def test_present_is_held_while_the_reindex_finalizes(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    """Even a manual trigger waits; it stays on the pair for the new PRESENT."""
    pair, future = pair_and_future
    present = get_current_search_settings(db_session)
    pair.indexing_trigger = IndexingMode.REINDEX
    db_session.commit()

    assert (
        should_index(pair, present, True, db_session, reindex_hold=_hold(future))
        is False
    )
    db_session.expire_all()
    assert pair.indexing_trigger == IndexingMode.REINDEX

    # Not finalizing: the trigger is honoured as before.
    not_held = ReindexHoldState(future_id=future.id, finalizing=False)
    assert should_index(pair, present, True, db_session, reindex_hold=not_held) is True


def test_future_starts_only_due_catch_up_polls_while_finalizing(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    assert pair.connector.refresh_freq is None  # a load-only pair polls anyway

    due = _pair_state(db_session, pair.id)
    assert (
        should_index(pair, future, True, db_session, reindex_hold=_hold(future, due))
        is True
    )

    writer_running = _pair_state(db_session, pair.id, present_active=True)
    assert (
        should_index(
            pair, future, True, db_session, reindex_hold=_hold(future, writer_running)
        )
        is False
    )

    now = get_db_current_time(db_session)
    caught_up = _pair_state(db_session, pair.id, future_covered_through=now)
    assert (
        should_index(
            pair, future, True, db_session, reindex_hold=_hold(future, caught_up)
        )
        is False
    )

    backing_off = _pair_state(
        db_session,
        pair.id,
        future_failed_streak=1,
        retry_after=now + timedelta(minutes=5),
    )
    assert (
        should_index(
            pair, future, True, db_session, reindex_hold=_hold(future, backing_off)
        )
        is False
    )

    abandoned = _pair_state(db_session, pair.id, future_failed_streak=3)
    assert abandoned.abandoned is True
    assert (
        should_index(
            pair, future, True, db_session, reindex_hold=_hold(future, abandoned)
        )
        is False
    )

    # A pair the hold knows nothing about has nothing to catch up on.
    assert (
        should_index(pair, future, True, db_session, reindex_hold=_hold(future))
        is False
    )


def test_waiting_present_attempt_is_not_dispatched_during_the_hold(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, _future = pair_and_future
    present = get_current_search_settings(db_session)
    create_index_attempt(pair.id, present.id, db_session)
    celery_app = MagicMock()

    with patch.object(docprocessing_tasks, "get_first_indexing_hold") as first_hold:
        dispatched = _dispatch_pair_waiting_attempt(
            celery_app,
            db_session,
            cc_pair_id=pair.id,
            search_settings=present,
            redis_client=get_redis_client(),
            tenant_id=get_current_tenant_id(),
            hold_active=True,
        )
    assert dispatched is False
    first_hold.assert_not_called()
    celery_app.send_task.assert_not_called()

    # Without the hold the dispatch goes on to the capability-check hold.
    with patch.object(
        docprocessing_tasks, "get_first_indexing_hold", return_value=object()
    ) as first_hold:
        assert (
            _dispatch_pair_waiting_attempt(
                celery_app,
                db_session,
                cc_pair_id=pair.id,
                search_settings=present,
                redis_client=get_redis_client(),
                tenant_id=get_current_tenant_id(),
                hold_active=False,
            )
            is False
        )
    first_hold.assert_called_once()


def test_abandoned_catch_up_alerts_admins_once_per_reindex(
    db_session: Session,
    pair_and_future: tuple[ConnectorCredentialPair, SearchSettings],
    admin: User,
) -> None:
    pair, future = pair_and_future
    abandoned = _pair_state(db_session, pair.id, future_failed_streak=3)
    hold = _hold(future, abandoned)

    def alerts() -> list[Notification]:
        db_session.expire_all()
        return list(
            db_session.scalars(
                select(Notification).where(
                    Notification.user_id == admin.id,
                    Notification.notif_type
                    == NotificationType.REINDEX_CATCH_UP_ABANDONED,
                )
            ).all()
        )

    _alert_abandoned_catch_up(db_session, hold)
    _alert_abandoned_catch_up(db_session, hold)
    (alert,) = alerts()
    assert alert.additional_data is not None
    assert alert.additional_data["cc_pair_id"] == pair.id
    assert alert.additional_data["search_settings_id"] == future.id
    assert pair.name is not None and pair.name in (alert.title or "")

    # A later reindex of the same connector alerts again.
    _alert_abandoned_catch_up(
        db_session,
        ReindexHoldState(future_id=future.id + 1, finalizing=True, pairs=hold.pairs),
    )
    assert len(alerts()) == 2

    # A pair whose catch-up attempt still runs is not abandoned, so no alert.
    running = _pair_state(
        db_session, pair.id, future_failed_streak=3, future_active=True
    )
    _alert_abandoned_catch_up(
        db_session,
        ReindexHoldState(
            future_id=future.id + 2, finalizing=True, pairs={pair.id: running}
        ),
    )
    assert len(alerts()) == 2
