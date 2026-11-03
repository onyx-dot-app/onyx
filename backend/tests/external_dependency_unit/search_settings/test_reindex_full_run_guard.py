"""External dependency unit tests for the full-run guard during a port-flow
reindex: a crawl from the beginning or a backfill on PRESENT adds documents an
incremental FUTURE catch-up never fetches, so the connector endpoints refuse them
while a port-flow FUTURE exists, and a reindex refuses to start while one is
pending (see `raise_if_port_reindex_in_progress` and `full_run_pending_cc_pairs`).
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.connectors.edit_plan.apply import _ensure_no_full_run_during_reindex
from onyx.connectors.edit_plan.models import EditStep, EditStepKind
from onyx.db.enums import SwitchoverType
from onyx.db.models import SearchSettings
from onyx.db.search_settings import (
    REINDEX_BLOCKS_FULL_RUN_MESSAGE,
    raise_if_port_reindex_in_progress,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings


@pytest.fixture
def legacy_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[SearchSettings, None, None]:
    future = make_future_search_settings(db_session, use_port_flow=False)
    try:
        yield future
    finally:
        db_session.rollback()
        db_session.delete(future)
        db_session.commit()


def _step(kind: EditStepKind) -> EditStep:
    return EditStep(kind=kind, required=False, reasons=[])


def test_full_runs_are_refused_only_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    # A legacy FUTURE crawls from scratch and needs no guard.
    raise_if_port_reindex_in_progress(db_session)

    legacy_future.use_port_flow = True
    db_session.commit()
    with pytest.raises(OnyxError) as excinfo:
        raise_if_port_reindex_in_progress(db_session)
    assert excinfo.value.error_code == OnyxErrorCode.CONFLICT
    assert REINDEX_BLOCKS_FULL_RUN_MESSAGE in str(excinfo.value.detail)

    # ACTIVE_ONLY ports too; INSTANT promotes at once and leaves no FUTURE row.
    legacy_future.switchover_type = SwitchoverType.ACTIVE_ONLY
    db_session.commit()
    with pytest.raises(OnyxError):
        raise_if_port_reindex_in_progress(db_session)


def test_edit_steps_that_recrawl_are_refused_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    legacy_future.use_port_flow = True
    db_session.commit()

    for kind in (
        EditStepKind.FULL_REINDEX,
        EditStepKind.FULL_REINDEX_THEN_PRUNE,
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.WINDOW_BACKFILL,
    ):
        with pytest.raises(OnyxError):
            _ensure_no_full_run_during_reindex(
                db_session, [_step(EditStepKind.PRUNE), _step(kind)]
            )

    # Incremental and metadata-only steps go through.
    _ensure_no_full_run_during_reindex(
        db_session,
        [
            _step(EditStepKind.RESTART_ATTEMPT),
            _step(EditStepKind.PRUNE),
            _step(EditStepKind.ACCESS_TYPE),
        ],
    )
