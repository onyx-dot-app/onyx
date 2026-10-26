from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential
from onyx.db.permission_sync_attempt import (
    create_doc_permission_sync_attempt,
    create_external_group_sync_attempt,
    mark_doc_permission_sync_attempt_failed,
    mark_external_group_sync_attempt_failed,
)
from tests.external_dependency_unit.conftest import create_test_user


def create_test_connector_credential_pair(
    db_session: Session,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
    access_type: AccessType = AccessType.PUBLIC,
) -> ConnectorCredentialPair:
    """Create a test connector credential pair for testing.

    Names carry a random suffix so repeated runs against the same scratch
    database do not collide.
    """
    suffix = uuid4().hex[:8]
    user = create_test_user(db_session, f"perm_sync_{suffix}")

    connector = Connector(
        name=f"Test {source.value} Connector {suffix}",
        source=source,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=datetime.now(timezone.utc),
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        credential_json={},
        user_id=user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()
    # Expire the credential so it reloads from DB with SensitiveValue wrapper
    db_session.expire(credential)

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"Test CC Pair {suffix}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
    )
    db_session.add(cc_pair)
    db_session.commit()

    return cc_pair


def create_finished_doc_permission_sync_attempt(
    cc_pair_id: int, db_session: Session
) -> int:
    """A cc_pair has at most one open attempt, so history is made of finished ones."""
    attempt_id = create_doc_permission_sync_attempt(cc_pair_id, db_session)
    mark_doc_permission_sync_attempt_failed(
        attempt_id, db_session, error_message="finished"
    )
    return attempt_id


def create_finished_external_group_sync_attempt(
    cc_pair_id: int, db_session: Session
) -> int:
    """A cc_pair has at most one open attempt, so history is made of finished ones."""
    attempt_id = create_external_group_sync_attempt(cc_pair_id, db_session)
    mark_external_group_sync_attempt_failed(
        attempt_id, db_session, error_message="finished"
    )
    return attempt_id
