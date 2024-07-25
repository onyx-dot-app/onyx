from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.connector import fetch_connector_by_id
from danswer.db.credentials import fetch_credential_by_id
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import EmbeddingModel
from danswer.db.models import IndexAttempt
from danswer.db.models import IndexingStatus
from danswer.db.models import IndexModelStatus
from danswer.db.models import User
from danswer.server.models import StatusResponse
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_connector_credential_pairs(
    db_session: Session, include_disabled: bool = True
) -> list[ConnectorCredentialPair]:
    stmt = select(ConnectorCredentialPair)
    if not include_disabled:
        stmt = stmt.where(ConnectorCredentialPair.connector.disabled == False)  # noqa
    results = db_session.scalars(stmt)
    return list(results.all())


def get_connector_credential_pair(
    connector_id: int,
    credential_id: int,
    db_session: Session,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = stmt.where(ConnectorCredentialPair.connector_id == connector_id)
    stmt = stmt.where(ConnectorCredentialPair.credential_id == credential_id)
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def get_connector_credential_pair_from_id(
    cc_pair_id: int,
    db_session: Session,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = stmt.where(ConnectorCredentialPair.id == cc_pair_id)
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def get_last_successful_attempt_time(
    connector_id: int,
    credential_id: int,
    embedding_model: EmbeddingModel,
    db_session: Session,
) -> float:
    """Gets the timestamp of the last successful index run stored in
    the CC Pair row in the database"""
    if embedding_model.status == IndexModelStatus.PRESENT:
        connector_credential_pair = get_connector_credential_pair(
            connector_id, credential_id, db_session
        )
        if (
            connector_credential_pair is None
            or connector_credential_pair.last_successful_index_time is None
        ):
            return 0.0

        return connector_credential_pair.last_successful_index_time.timestamp()

    # For Secondary Index we don't keep track of the latest success, so have to calculate it live
    attempt = (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.connector_id == connector_id,
            IndexAttempt.credential_id == credential_id,
            IndexAttempt.embedding_model_id == embedding_model.id,
            IndexAttempt.status == IndexingStatus.SUCCESS,
        )
        .order_by(IndexAttempt.time_started.desc())
        .first()
    )

    if not attempt or not attempt.time_started:
        return 0.0

    return attempt.time_started.timestamp()


def update_connector_credential_pair(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    net_docs: int | None = None,
    run_dt: datetime | None = None,
) -> None:
    cc_pair = get_connector_credential_pair(connector_id, credential_id, db_session)
    if not cc_pair:
        logger.warning(
            f"Attempted to update pair for connector id {connector_id} "
            f"and credential id {credential_id}"
        )
        return
    # simply don't update last_successful_index_time if run_dt is not specified
    # at worst, this would result in re-indexing documents that were already indexed
    if run_dt is not None:
        cc_pair.last_successful_index_time = run_dt
    if net_docs is not None:
        cc_pair.total_docs_indexed += net_docs
    db_session.commit()


def delete_connector_credential_pair__no_commit(
    db_session: Session,
    connector_id: int,
    credential_id: int,
) -> None:
    stmt = delete(ConnectorCredentialPair).where(
        ConnectorCredentialPair.connector_id == connector_id,
        ConnectorCredentialPair.credential_id == credential_id,
    )
    db_session.execute(stmt)


def associate_default_cc_pair(db_session: Session) -> None:
    existing_association = (
        db_session.query(ConnectorCredentialPair)
        .filter(
            ConnectorCredentialPair.connector_id == 0,
            ConnectorCredentialPair.credential_id == 0,
        )
        .one_or_none()
    )
    if existing_association is not None:
        return

    association = ConnectorCredentialPair(
        connector_id=0,
        credential_id=0,
        name="DefaultCCPair",
    )
    db_session.add(association)
    db_session.commit()


def add_credential_to_connector(
    connector_id: int,
    credential_id: int,
    cc_pair_name: str | None,
    is_public: bool,
    user: User | None,
    db_session: Session,
) -> StatusResponse[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    credential = fetch_credential_by_id(credential_id, user, db_session)

    if connector is None:
        raise HTTPException(status_code=404, detail="Connector does not exist")

    if credential is None:
        raise HTTPException(
            status_code=401,
            detail="Credential does not exist or does not belong to user",
        )

    existing_association = (
        db_session.query(ConnectorCredentialPair)
        .filter(
            ConnectorCredentialPair.connector_id == connector_id,
            ConnectorCredentialPair.credential_id == credential_id,
        )
        .one_or_none()
    )
    if existing_association is not None:
        return StatusResponse(
            success=False,
            message=f"Connector already has Credential {credential_id}",
            data=connector_id,
        )

    association = ConnectorCredentialPair(
        connector_id=connector_id,
        credential_id=credential_id,
        name=cc_pair_name,
        is_public=is_public,
    )
    db_session.add(association)
    db_session.commit()

    return StatusResponse(
        success=True,
        message=f"New Credential {credential_id} added to Connector",
        data=connector_id,
    )


def remove_credential_from_connector(
    connector_id: int,
    credential_id: int,
    user: User | None,
    db_session: Session,
) -> StatusResponse[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    credential = fetch_credential_by_id(credential_id, user, db_session)

    if connector is None:
        raise HTTPException(status_code=404, detail="Connector does not exist")

    if credential is None:
        raise HTTPException(
            status_code=404,
            detail="Credential does not exist or does not belong to user",
        )

    association = (
        db_session.query(ConnectorCredentialPair)
        .filter(
            ConnectorCredentialPair.connector_id == connector_id,
            ConnectorCredentialPair.credential_id == credential_id,
        )
        .one_or_none()
    )

    if association is not None:
        db_session.delete(association)
        db_session.commit()
        return StatusResponse(
            success=True,
            message=f"Credential {credential_id} removed from Connector",
            data=connector_id,
        )

    return StatusResponse(
        success=False,
        message=f"Connector already does not have Credential {credential_id}",
        data=connector_id,
    )


def resync_cc_pair(
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
) -> None:
    def find_latest_index_attempt(
        connector_id: int,
        credential_id: int,
        only_include_success: bool,
        db_session: Session,
    ) -> IndexAttempt | None:
        query = (
            db_session.query(IndexAttempt)
            .join(EmbeddingModel, IndexAttempt.embedding_model_id == EmbeddingModel.id)
            .filter(
                IndexAttempt.connector_id == connector_id,
                IndexAttempt.credential_id == credential_id,
                EmbeddingModel.status == IndexModelStatus.PRESENT,
            )
        )

        if only_include_success:
            query = query.filter(IndexAttempt.status == IndexingStatus.SUCCESS)

        latest_index_attempt = query.order_by(desc(IndexAttempt.time_started)).first()

        return latest_index_attempt

    last_success = find_latest_index_attempt(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        only_include_success=True,
        db_session=db_session,
    )

    cc_pair.last_successful_index_time = (
        last_success.time_started if last_success else None
    )

    db_session.commit()
