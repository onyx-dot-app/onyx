from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

import onyx.db.index_attempt as index_attempt_module
from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.background.celery.tasks.pruning.tasks import _is_pruning_due
from onyx.background.celery.tasks.shared.tasks import _reindex_blocks_cleanup
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import create_index_attempt
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.models import ConnectorCredentialPair
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


def test_reindex_requirement_forces_indexing_and_blocks_pruning(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    search_settings = get_current_search_settings(db_session)
    cc_pair.reindex_required_since = datetime.now(timezone.utc)
    cc_pair.connector.refresh_freq = None
    db_session.commit()

    assert should_index(cc_pair, search_settings, False, db_session)
    assert not _is_pruning_due(cc_pair)
    assert _reindex_blocks_cleanup(
        db_session,
        cc_pair.connector_id,
        cc_pair.credential_id,
    )

    cc_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.flush()
    assert not _reindex_blocks_cleanup(
        db_session,
        cc_pair.connector_id,
        cc_pair.credential_id,
    )


def _create_required_reindex(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> int:
    search_settings = get_current_search_settings(db_session)
    cc_pair.reindex_required_since = datetime.now(timezone.utc)
    db_session.commit()
    requirement_started_at = cc_pair.reindex_required_since
    assert requirement_started_at is not None
    return create_index_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        db_session=db_session,
        from_beginning=True,
        reindex_requirement_started_at=requirement_started_at,
    )


def test_successful_current_reindex_clears_requirement(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    mark_attempt_succeeded(_create_required_reindex(db_session, cc_pair), db_session)
    updated_pair = get_connector_credential_pair_from_id(
        db_session,
        cc_pair.id,
    )
    assert updated_pair is not None
    assert updated_pair.reindex_required_since is None


def test_partially_successful_reindex_keeps_requirement(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    mark_attempt_partially_succeeded(
        _create_required_reindex(db_session, cc_pair),
        db_session,
    )
    updated_pair = get_connector_credential_pair_from_id(db_session, cc_pair.id)
    assert updated_pair is not None
    assert updated_pair.reindex_required_since is not None


def test_successful_reindex_keeps_requirement_while_pruning(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        index_attempt_module,
        "RedisConnector",
        lambda *_: SimpleNamespace(prune=SimpleNamespace(fenced=True)),
    )
    mark_attempt_succeeded(_create_required_reindex(db_session, cc_pair), db_session)

    updated_pair = get_connector_credential_pair_from_id(db_session, cc_pair.id)
    assert updated_pair is not None
    assert updated_pair.reindex_required_since is not None


def test_attempt_started_before_requirement_does_not_clear_it(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    search_settings = get_current_search_settings(db_session)
    attempt_id = create_index_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        db_session=db_session,
        from_beginning=True,
    )
    cc_pair.reindex_required_since = datetime.now(timezone.utc)
    db_session.commit()

    mark_attempt_succeeded(attempt_id, db_session)

    updated_pair = get_connector_credential_pair_from_id(db_session, cc_pair.id)
    assert updated_pair is not None
    assert updated_pair.reindex_required_since is not None
