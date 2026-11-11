"""Resolve All narrowed to status groups: the activity panel's Running level
resolves only its running runs, on the pair routes and the fleet routes."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import CCPairRunStatusGroup, IndexingStatus
from onyx.db.models import ConnectorCredentialPair, User
from onyx.server.documents.cc_pair import (
    get_resolvable_cc_pair_runs_count,
    resolve_matching_cc_pair_runs,
)
from onyx.server.documents.index_monitoring import (
    get_resolvable_indexing_runs_count,
    resolve_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
)
from tests.external_dependency_unit.indexing.test_cc_pair_errors_resolve_route import (
    _assert_open,
    _assert_resolved_without_retry,
    _attempt,
    _error,
    admin,  # noqa: F401
    pairs,  # noqa: F401
)

# The pair feed lists perm sync kinds, which come from EE-only helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_Pairs = tuple[ConnectorCredentialPair, ConnectorCredentialPair]
_RUNNING: list[CCPairRunStatusGroup] = [CCPairRunStatusGroup.RUNNING]


def _settled_and_running_errors(
    db_session: Session, pair: ConnectorCredentialPair
) -> tuple[int, int]:
    """(an open error of a succeeded run, an open error of a later running run).
    The running run is newer, so neither run supersedes the other."""
    succeeded = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    settled_error = _error(db_session, succeeded, "settled-doc")
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    running_error = _error(db_session, running, "running-doc")
    return settled_error, running_error


def test_pair_resolve_all_on_running_resolves_running_runs_only(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    settled_error, running_error = _settled_and_running_errors(db_session, pair)

    count = get_resolvable_cc_pair_runs_count(
        cc_pair_id=pair.id,
        level=CCPairRunLevel.ERRORS,
        q=None,
        since=None,
        until=None,
        kinds=None,
        status_groups=_RUNNING,
        user=admin,
        db_session=db_session,
    ).count
    assert count == 1

    response = resolve_matching_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveMatchingRequest(
            level=CCPairRunLevel.ERRORS, status_groups=_RUNNING
        ),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 1
    _assert_resolved_without_retry(db_session, running_error)
    _assert_open(db_session, settled_error)


def test_fleet_resolve_all_on_running_resolves_running_runs_only(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, other = pairs
    settled_error, running_error = _settled_and_running_errors(db_session, pair)
    failed = _attempt(db_session, other, IndexingStatus.FAILED)
    failed_error = _error(db_session, failed, "failed-doc")
    cc_pair_ids = [pair.id, other.id]

    # Every level, so the Failures level's run is in scope until the groups narrow it.
    count = get_resolvable_indexing_runs_count(
        level=None,
        q=None,
        since=None,
        until=None,
        kinds=None,
        cc_pair_ids=cc_pair_ids,
        status_groups=_RUNNING,
        user=admin,
        db_session=db_session,
    ).count
    assert count == 1

    response = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(
            cc_pair_ids=cc_pair_ids, status_groups=_RUNNING
        ),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 1
    assert response.cc_pair_ids == [pair.id]
    _assert_resolved_without_retry(db_session, running_error)
    _assert_open(db_session, settled_error)
    _assert_open(db_session, failed_error)
