"""Helpers for daily targeted-reindex integration tests.

Each helper writes the minimum DB state needed to drive the targeted-
reindex flow against a real Drive cc_pair: a connector + credential +
cc_pair tied to the Drive service account, a parent IndexAttempt to
hang errors off of, and an IndexAttemptError pointing at a known doc.
"""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.search_settings import get_current_search_settings

_ADMIN_EMAIL = "admin@onyx-test.com"


def _parse_credentials(env_str: str) -> dict[str, Any]:
    """Service account JSON arrives from AWS secrets either as a plain
    JSON string or as a double-escaped one (depending on how the secret
    was stored). Try the plain form first, fall back to unescaping only
    on a JSON parse failure so any other exception (e.g. missing secret
    surfacing as a TypeError) propagates cleanly."""
    try:
        return json.loads(env_str)
    except json.JSONDecodeError:
        unescaped = env_str.replace('\\"', '"').strip('"')
        return json.loads(unescaped)


def make_drive_cc_pair(
    db_session: Session, service_account_json_str: str
) -> ConnectorCredentialPair:
    """Persist a Drive cc_pair using the service account credential.

    Connector config is intentionally minimal — `Resolver.reindex` only
    needs valid auth and a primary admin email; it doesn't crawl.
    """
    refried = json.dumps(_parse_credentials(service_account_json_str))
    credential_json: dict[str, Any] = {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: refried,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: _ADMIN_EMAIL,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: (
            GoogleOAuthAuthenticationMethod.UPLOADED.value
        ),
    }

    connector = Connector(
        name="targeted-reindex-integration-drive-%s" % uuid4().hex[:8],
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={"include_files_shared_with_me": True},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json=credential_json,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()

    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="targeted-reindex-integration-cc-%s" % uuid4().hex[:8],
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(pair)
    db_session.commit()
    db_session.refresh(pair)
    return pair


def make_failed_index_attempt(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> IndexAttempt:
    """Parent IndexAttempt for IndexAttemptError rows to FK against.
    Status FAILED is required because IndexAttemptError can only attach
    to non-success attempts in production."""
    settings = get_current_search_settings(db_session)
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def make_index_attempt_error(
    db_session: Session,
    parent: IndexAttempt,
    document_id: str,
    failure_message: str = "synthetic test failure",
) -> IndexAttemptError:
    err = IndexAttemptError(
        index_attempt_id=parent.id,
        connector_credential_pair_id=parent.connector_credential_pair_id,
        document_id=document_id,
        document_link=document_id if document_id.startswith("http") else None,
        failure_message=failure_message,
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)
    return err


def cleanup_targeted_reindex_state(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Tear down everything created during one integration test.

    Scoped to this cc_pair only so the cleanup is safe in a shared test
    DB. We discover the job ids touched by this run via the
    `targeted_reindex_job_target` table (each row carries `cc_pair_id`),
    then delete in FK-safe order:
    targeted_reindex_job_target → targeted_reindex_job →
    index_attempt_errors → index_attempt → cc_pair → connector +
    credential.
    """
    db_session.expire_all()

    job_ids: list[int] = [
        row[0]
        for row in db_session.query(TargetedReindexJobTarget.targeted_reindex_job_id)
        .filter(TargetedReindexJobTarget.cc_pair_id == cc_pair.id)
        .distinct()
        .all()
    ]

    db_session.query(TargetedReindexJobTarget).filter(
        TargetedReindexJobTarget.cc_pair_id == cc_pair.id
    ).delete(synchronize_session="fetch")
    if job_ids:
        db_session.query(TargetedReindexJob).filter(
            TargetedReindexJob.id.in_(job_ids)
        ).delete(synchronize_session="fetch")
    db_session.query(IndexAttemptError).filter(
        IndexAttemptError.connector_credential_pair_id == cc_pair.id
    ).delete(synchronize_session="fetch")
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == cc_pair.id
    ).delete(synchronize_session="fetch")

    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id
    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.id == cc_pair.id
    ).delete(synchronize_session="fetch")
    db_session.query(Connector).filter(Connector.id == connector_id).delete(
        synchronize_session="fetch"
    )
    db_session.query(Credential).filter(Credential.id == credential_id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()
