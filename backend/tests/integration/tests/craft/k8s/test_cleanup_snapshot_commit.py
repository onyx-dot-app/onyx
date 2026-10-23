"""Keep the last committed archive when PostgreSQL rejects a snapshot commit."""

from uuid import uuid4

import httpx
import pytest
from kubernetes import client
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_NAMESPACE,
    SandboxBackend,
)
from onyx.server.features.build.db.sandbox import (
    get_latest_snapshot_for_session,
    get_snapshots_for_session,
)
from tests.common.craft.cleanup_worker import (
    isolated_cleanup_deployment as isolated_cleanup_deployment,
)
from tests.common.craft.cleanup_worker import require_isolated_cleanup_deployment
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.tests.craft.k8s.k8s_fixtures import OwnedLivePod, pod_exec

require_isolated_cleanup_deployment()
pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES, reason="Kubernetes only"
    ),
    pytest.mark.usefixtures("isolated_cleanup_deployment", "tenant_context"),
]


def test_failed_snapshot_commit_preserves_the_committed_archive(
    owned_live_pod: OwnedLivePod,
    k8s_client: client.CoreV1Api,
    db_session: Session,
) -> None:
    owned = owned_live_pod
    path = f"/workspace/sessions/{owned.session_id}/outputs/checkpoint.txt"
    pod_exec(
        k8s_client,
        owned.pod_name,
        SANDBOX_NAMESPACE,
        f"printf previous-checkpoint > {path}",
    )
    previous = BuildSessionManager.create_snapshot(owned.api_user, owned.session_id)
    assert previous is not None

    name = f"cleanup_commit_{uuid4().hex}"
    db_session.execute(
        text(f"""
        CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'injected snapshot commit failure'; END;
        $$
    """)
    )
    db_session.execute(
        text(f"""
        CREATE CONSTRAINT TRIGGER {name}
        AFTER INSERT ON snapshot DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.session_id = '{owned.session_id}'::uuid)
        EXECUTE FUNCTION {name}()
    """)
    )
    db_session.commit()

    committed_before_failure = get_snapshots_for_session(db_session, owned.session_id)
    assert len(committed_before_failure) == 1
    committed_storage_path = committed_before_failure[0].storage_path
    store = get_default_file_store()
    with store.read_file(committed_storage_path, use_tempfile=True) as archive:
        original_bytes = archive.read()
    assert original_bytes

    try:
        pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"printf newer-uncommitted-work > {path}",
        )

        with pytest.raises(httpx.HTTPStatusError) as error:
            BuildSessionManager.create_snapshot(owned.api_user, owned.session_id)
        assert error.value.response.status_code == 500

        db_session.expire_all()
        committed = get_latest_snapshot_for_session(db_session, owned.session_id)
        assert committed is not None
        assert committed.storage_path == committed_storage_path
        assert len(get_snapshots_for_session(db_session, owned.session_id)) == 1
        with store.read_file(committed_storage_path, use_tempfile=True) as archive:
            assert archive.read() == original_bytes
    finally:
        db_session.rollback()
        db_session.execute(text(f"DROP TRIGGER {name} ON snapshot"))
        db_session.execute(text(f"DROP FUNCTION {name}()"))
        db_session.commit()

    replacement = BuildSessionManager.create_snapshot(owned.api_user, owned.session_id)
    assert replacement is not None
    assert replacement.storage_path != committed_storage_path
    db_session.expire_all()
    committed = get_latest_snapshot_for_session(db_session, owned.session_id)
    assert committed is not None
    assert committed.storage_path == replacement.storage_path
