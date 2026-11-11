"""Two GitHub connectors on one credential: one PUBLIC, one perm synced. The
public pair's capability checks find nothing in scope for group sync. Its
report must not stop group sync for the synced pair."""

from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.external_group_syncing import (
    tasks as group_tasks,
)
from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import indexing_hold
from onyx.connectors.capability_checks.indexing_hold import get_first_indexing_hold
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckNotRunReason,
    CredentialCapabilityReport,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.github.capability_checks import build_github_group_sync_checks
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.credential_capability import upsert_completed_capability_report
from onyx.db.enums import (
    AccessType,
    CapabilityCheckTrigger,
    ConnectorCredentialPairStatus,
    PermissionSyncStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    ExternalGroupPermissionSyncAttempt,
    User,
    User__ExternalUserGroupId,
)
from onyx.db.permission_sync_attempt import (
    get_external_group_sync_attempt,
    try_create_external_group_sync_attempt,
)
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_TRIGGER = CapabilityCheckTrigger.CC_PAIR_VALIDATION
_CONFIG: dict[str, str] = {"repo_owner": "onyx-dot-app", "repositories": ""}


class _Pairs:
    def __init__(
        self,
        user: User,
        credential: Credential,
        public: ConnectorCredentialPair,
        synced: ConnectorCredentialPair,
    ) -> None:
        self.user = user
        self.credential = credential
        self.public = public
        self.synced = synced


def _add_pair(
    db_session: Session, credential: Credential, access_type: AccessType
) -> ConnectorCredentialPair:
    suffix = uuid4().hex[:8]
    connector = Connector(
        name=f"github-{access_type.value}-{suffix}",
        source=DocumentSource.GITHUB,
        input_type=InputType.POLL,
        connector_specific_config=_CONFIG,
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=connector.name,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
    )
    db_session.add(cc_pair)
    db_session.flush()
    return cc_pair


def _store_group_report(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: CapabilityCheckStatus,
    connector_id: int | None,
) -> None:
    """Stores the group-sync checks of a run with one status for all."""
    results: list[CapabilityCheckResult] = [
        CapabilityCheckResult(
            capability=check.capability,
            check_id=check.check_id,
            display_name=check.display_name,
            required=check.required,
            status=status,
            not_run_reason=(
                CheckNotRunReason.NOTHING_IN_SCOPE
                if status == CapabilityCheckStatus.SKIPPED
                else None
            ),
        )
        for check in build_github_group_sync_checks()
    ]
    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=connector_id,
        source=DocumentSource.GITHUB,
        trigger=_TRIGGER,
        report=CredentialCapabilityReport(
            credential_id=cc_pair.credential_id,
            source=DocumentSource.GITHUB,
            connector_id=connector_id,
            checked_at=datetime.now(timezone.utc),
            trigger=_TRIGGER,
            verdicts={},
            check_results=results,
        ),
        connector_config_hash=(
            compute_connector_config_hash(_CONFIG) if connector_id else None
        ),
    )


@pytest.fixture
def pairs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Pairs, None, None]:
    user = create_test_user(db_session, "github_mixed_access")
    credential = Credential(
        source=DocumentSource.GITHUB, credential_json={}, user_id=user.id
    )
    db_session.add(credential)
    db_session.flush()
    # The public pair is created first, so it has the lower id.
    public = _add_pair(db_session, credential, AccessType.PUBLIC)
    synced = _add_pair(db_session, credential, AccessType.SYNC)
    db_session.commit()

    # The public repositories leave group sync nothing to test, on the public
    # pair's own run and on the shared credential's run.
    _store_group_report(
        db_session, public, CapabilityCheckStatus.SKIPPED, public.connector_id
    )
    _store_group_report(db_session, public, CapabilityCheckStatus.SKIPPED, None)
    _store_group_report(
        db_session, synced, CapabilityCheckStatus.PASSED, synced.connector_id
    )
    db_session.commit()

    yield _Pairs(user=user, credential=credential, public=public, synced=synced)

    db_session.rollback()
    pair_ids: list[int] = [public.id, synced.id]
    db_session.execute(
        delete(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.cc_pair_id.in_(pair_ids)
        )
    )
    db_session.execute(
        delete(ExternalGroupPermissionSyncAttempt).where(
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(
                pair_ids
            )
        )
    )
    db_session.execute(
        delete(ConnectorCredentialPair).where(ConnectorCredentialPair.id.in_(pair_ids))
    )
    db_session.execute(
        delete(Connector).where(
            Connector.id.in_([public.connector_id, synced.connector_id])
        )
    )
    # Cascades the capability reports.
    db_session.execute(delete(Credential).where(Credential.id == credential.id))
    delete_test_user(db_session, user)
    db_session.commit()


def test_public_pair_checks_do_not_stop_group_sync_for_the_synced_pair(
    pairs: _Pairs, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indexing_hold, "CONNECTOR_CHECKS_ENABLED", True)
    synced_id: int = pairs.synced.id

    # The beat dispatches group sync for the synced pair only.
    dispatched: list[int] = []
    with (
        patch.object(group_tasks, "fail_lost_queued_external_group_sync_attempts"),
        patch.object(
            group_tasks,
            "try_creating_external_group_sync_task",
            side_effect=lambda _app, cc_pair_id, _tenant_id: dispatched.append(
                cc_pair_id
            ),
        ),
    ):
        group_tasks.check_for_external_group_sync.apply(
            kwargs={"tenant_id": TEST_TENANT_ID}
        ).get()
    assert synced_id in dispatched
    assert pairs.public.id not in dispatched

    # Neither pair's first index attempt is held.
    db_session.expire_all()
    assert get_first_indexing_hold(db_session, pairs.synced) is None
    assert get_first_indexing_hold(db_session, pairs.public) is None

    # The dispatched task runs the synced pair's group sync to completion.
    attempt_id = try_create_external_group_sync_attempt(
        synced_id, f"task-{uuid4().hex[:8]}", db_session
    )
    assert attempt_id is not None
    synced_pairs: list[int] = []

    def _fake_group_sync(
        tenant_id: str,  # noqa: ARG001
        cc_pair: ConnectorCredentialPair,
    ) -> Generator[ExternalUserGroup, None, None]:
        synced_pairs.append(cc_pair.id)
        yield ExternalUserGroup(id="private-repo", user_emails=[pairs.user.email])

    sync_config = Mock()
    sync_config.group_sync_config.group_sync_func = _fake_group_sync
    with patch.object(
        group_tasks, "get_source_perm_sync_config", return_value=sync_config
    ):
        group_tasks.connector_external_group_sync_generator_task.apply(
            args=(synced_id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()

    assert synced_pairs == [synced_id]
    db_session.expire_all()
    attempt = get_external_group_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.SUCCESS, attempt.error_message
    assert attempt.total_groups_processed == 1
    synced = get_connector_credential_pair_from_id(db_session, synced_id)
    assert synced is not None and synced.last_time_external_group_sync is not None
