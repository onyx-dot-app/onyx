"""Pairs, attempts and feed reads shared by the run feed tests."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
    TargetedReindexJob,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import get_cc_pair_runs
from onyx.server.documents.models import CCPairRunsResponse
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair


def run_mark(prefix: str) -> str:
    """Earlier runs leave rows behind, so each test marks its runs and searches by it."""
    return f"{prefix}-{uuid4().hex}"


class RunFeedRecords:
    """What a test creates, torn down in FK order."""

    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.pairs: list[ConnectorCredentialPair] = []
        self.job_ids: list[int] = []
        self.settings_ids: list[int] = []
        self.users: list[User] = []

    def user(self, prefix: str, is_admin: bool = False) -> User:
        user = create_test_user(self.db_session, prefix, is_admin=is_admin)
        self.users.append(user)
        return user

    def pair(
        self,
        name: str,
        access_type: AccessType = AccessType.PUBLIC,
        creator: User | None = None,
    ) -> ConnectorCredentialPair:
        creator_id = None if creator is None else creator.id
        connector = Connector(
            name="Run Feed Connector",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=None,
        )
        self.db_session.add(connector)
        self.db_session.flush()
        credential = Credential(
            credential_json={}, user_id=creator_id, admin_public=True
        )
        self.db_session.add(credential)
        self.db_session.flush()
        pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=name,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=access_type,
            creator_id=creator_id,
        )
        self.db_session.add(pair)
        self.db_session.commit()
        self.pairs.append(pair)
        return pair

    def job(self) -> TargetedReindexJob:
        job = TargetedReindexJob()
        self.db_session.add(job)
        self.db_session.commit()
        self.job_ids.append(job.id)
        return job

    def cleanup(self) -> None:
        self.db_session.rollback()
        for pair in self.pairs:
            # IndexAttemptError has no FK cascade, so its rows go first.
            for model in (IndexAttemptError, IndexAttempt):
                self.db_session.query(model).filter(
                    model.connector_credential_pair_id == pair.id
                ).delete(synchronize_session="fetch")
        self.db_session.query(TargetedReindexJob).filter(
            TargetedReindexJob.id.in_(self.job_ids)
        ).delete(synchronize_session="fetch")
        self.db_session.query(SearchSettings).filter(
            SearchSettings.id.in_(self.settings_ids)
        ).delete(synchronize_session="fetch")
        self.db_session.commit()
        for pair in self.pairs:
            cleanup_cc_pair(self.db_session, pair)
        for user in self.users:
            delete_test_user(self.db_session, user)
        self.db_session.commit()


def make_index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    created: datetime,
    status: IndexingStatus,
    mark: str,
    job: TargetedReindexJob | None = None,
    search_settings_id: int | None = None,
) -> IndexAttempt:
    """An attempt created at ``created``, carrying ``mark`` as its error text."""
    if search_settings_id is None:
        search_settings_id = get_current_search_settings(db_session).id
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=status,
        error_msg=mark,
        targeted_reindex_job_id=None if job is None else job.id,
        time_started=None if status == IndexingStatus.NOT_STARTED else created,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = created
    db_session.commit()
    return attempt


def read_pair_feed(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    since: datetime | None = None,
    until: datetime | None = None,
    kinds: list[CCPairRunKind] | None = None,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    q: str | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=10,
        since=since,
        until=until,
        kinds=kinds,
        status_groups=status_groups,
        q=q,
        errors=None,
        superseded=None,
        resolved=None,
        user=user,
        db_session=db_session,
    )
