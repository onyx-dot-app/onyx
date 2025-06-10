from datetime import datetime
from datetime import timezone
from typing import cast

from sqlalchemy import and_
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DEFAULT_PRUNING_FREQ
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import IndexingMode
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.kg.models import KGConnectorData
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import ObjectCreationIdResponse
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()


def check_connectors_exist(db_session: Session) -> bool:
    # Connector 0 is created on server startup as a default for ingestion
    # it will always exist and we don't need to count it for this
    stmt = select(exists(Connector).where(Connector.id > 0))
    result = db_session.execute(stmt)
    return result.scalar() or False


def fetch_connectors(
    db_session: Session,
    sources: list[DocumentSource] | None = None,
    input_types: list[InputType] | None = None,
) -> list[Connector]:
    stmt = select(Connector)
    if sources is not None:
        stmt = stmt.where(Connector.source.in_(sources))
    if input_types is not None:
        stmt = stmt.where(Connector.input_type.in_(input_types))
    results = db_session.scalars(stmt)
    return list(results.all())


def connector_by_name_source_exists(
    connector_name: str, source: DocumentSource, db_session: Session
) -> bool:
    stmt = select(Connector).where(
        Connector.name == connector_name, Connector.source == source
    )
    result = db_session.execute(stmt)
    connector = result.scalar_one_or_none()
    return connector is not None


def fetch_connector_by_id(connector_id: int, db_session: Session) -> Connector | None:
    stmt = select(Connector).where(Connector.id == connector_id)
    result = db_session.execute(stmt)
    connector = result.scalar_one_or_none()
    return connector


def fetch_ingestion_connector_by_name(
    connector_name: str, db_session: Session
) -> Connector | None:
    stmt = (
        select(Connector)
        .where(Connector.name == connector_name)
        .where(Connector.source == DocumentSource.INGESTION_API)
    )
    result = db_session.execute(stmt)
    connector = result.scalar_one_or_none()
    return connector


def create_connector(
    db_session: Session,
    connector_data: ConnectorBase,
) -> ObjectCreationIdResponse:
    if connector_by_name_source_exists(
        connector_data.name, connector_data.source, db_session
    ):
        raise ValueError(
            "Connector by this name already exists, duplicate naming not allowed."
        )

    connector = Connector(
        name=connector_data.name,
        source=connector_data.source,
        input_type=connector_data.input_type,
        connector_specific_config=connector_data.connector_specific_config,
        refresh_freq=connector_data.refresh_freq,
        indexing_start=connector_data.indexing_start,
        prune_freq=connector_data.prune_freq,
    )
    db_session.add(connector)
    db_session.commit()

    return ObjectCreationIdResponse(id=connector.id)


def update_connector(
    connector_id: int,
    connector_data: ConnectorBase,
    db_session: Session,
) -> Connector | None:
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        return None

    if connector_data.name != connector.name and connector_by_name_source_exists(
        connector_data.name, connector_data.source, db_session
    ):
        raise ValueError(
            "Connector by this name already exists, duplicate naming not allowed."
        )

    connector.name = connector_data.name
    connector.source = connector_data.source
    connector.input_type = connector_data.input_type
    connector.connector_specific_config = connector_data.connector_specific_config
    connector.refresh_freq = connector_data.refresh_freq
    connector.prune_freq = (
        connector_data.prune_freq
        if connector_data.prune_freq is not None
        else DEFAULT_PRUNING_FREQ
    )

    db_session.commit()
    return connector


def delete_connector(
    db_session: Session,
    connector_id: int,
) -> StatusResponse[int]:
    """Only used in special cases (e.g. a connector is in a bad state and we need to delete it).
    Be VERY careful using this, as it could lead to a bad state if not used correctly.
    """
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        return StatusResponse(
            success=True, message="Connector was already deleted", data=connector_id
        )

    db_session.delete(connector)
    return StatusResponse(
        success=True, message="Connector deleted successfully", data=connector_id
    )


def get_connector_credential_ids(
    connector_id: int,
    db_session: Session,
) -> list[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        raise ValueError(f"Connector by id {connector_id} does not exist")

    return [association.credential.id for association in connector.credentials]


def fetch_latest_index_attempt_by_connector(
    db_session: Session,
    source: DocumentSource | None = None,
) -> list[IndexAttempt]:
    latest_index_attempts: list[IndexAttempt] = []

    if source:
        connectors = fetch_connectors(db_session, sources=[source])
    else:
        connectors = fetch_connectors(db_session)

    if not connectors:
        return []

    for connector in connectors:
        latest_index_attempt = (
            db_session.query(IndexAttempt)
            .join(ConnectorCredentialPair)
            .filter(ConnectorCredentialPair.connector_id == connector.id)
            .order_by(IndexAttempt.time_updated.desc())
            .first()
        )

        if latest_index_attempt is not None:
            latest_index_attempts.append(latest_index_attempt)

    return latest_index_attempts


def fetch_latest_index_attempts_by_status(
    db_session: Session,
) -> list[IndexAttempt]:
    subquery = (
        db_session.query(
            IndexAttempt.connector_credential_pair_id,
            IndexAttempt.status,
            func.max(IndexAttempt.time_updated).label("time_updated"),
        )
        .group_by(IndexAttempt.connector_credential_pair_id)
        .group_by(IndexAttempt.status)
        .subquery()
    )

    alias = aliased(IndexAttempt, subquery)

    query = db_session.query(IndexAttempt).join(
        alias,
        and_(
            IndexAttempt.connector_credential_pair_id
            == alias.connector_credential_pair_id,
            IndexAttempt.status == alias.status,
            IndexAttempt.time_updated == alias.time_updated,
        ),
    )

    return cast(list[IndexAttempt], query.all())


def fetch_unique_document_sources(db_session: Session) -> list[DocumentSource]:
    distinct_sources = db_session.query(Connector.source).distinct().all()

    sources = [
        source[0]
        for source in distinct_sources
        if source[0] != DocumentSource.INGESTION_API
    ]

    return sources


def create_initial_default_connector(db_session: Session) -> None:
    default_connector_id = 0
    default_connector = fetch_connector_by_id(default_connector_id, db_session)
    if default_connector is not None:
        if (
            default_connector.source != DocumentSource.INGESTION_API
            or default_connector.input_type != InputType.LOAD_STATE
            or default_connector.refresh_freq is not None
            or default_connector.name != "Ingestion API"
            or default_connector.connector_specific_config != {}
            or default_connector.prune_freq is not None
        ):
            logger.warning(
                "Default connector does not have expected values. Updating to proper state."
            )
            # Ensure default connector has correct values
            default_connector.source = DocumentSource.INGESTION_API
            default_connector.input_type = InputType.LOAD_STATE
            default_connector.refresh_freq = None
            default_connector.name = "Ingestion API"
            default_connector.connector_specific_config = {}
            default_connector.prune_freq = None
            db_session.commit()
        return

    # Create a new default connector if it doesn't exist
    connector = Connector(
        id=default_connector_id,
        name="Ingestion API",
        source=DocumentSource.INGESTION_API,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
    )
    db_session.add(connector)
    db_session.commit()


def mark_ccpair_as_pruned(cc_pair_id: int, db_session: Session) -> None:
    stmt = select(ConnectorCredentialPair).where(
        ConnectorCredentialPair.id == cc_pair_id
    )
    cc_pair = db_session.scalar(stmt)
    if cc_pair is None:
        raise ValueError(f"No cc_pair with ID: {cc_pair_id}")

    cc_pair.last_pruned = datetime.now(timezone.utc)
    db_session.commit()


def mark_cc_pair_as_permissions_synced(
    db_session: Session, cc_pair_id: int, start_time: datetime | None
) -> None:
    stmt = select(ConnectorCredentialPair).where(
        ConnectorCredentialPair.id == cc_pair_id
    )
    cc_pair = db_session.scalar(stmt)
    if cc_pair is None:
        raise ValueError(f"No cc_pair with ID: {cc_pair_id}")

    cc_pair.last_time_perm_sync = start_time
    db_session.commit()


def mark_cc_pair_as_external_group_synced(db_session: Session, cc_pair_id: int) -> None:
    stmt = select(ConnectorCredentialPair).where(
        ConnectorCredentialPair.id == cc_pair_id
    )
    cc_pair = db_session.scalar(stmt)
    if cc_pair is None:
        raise ValueError(f"No cc_pair with ID: {cc_pair_id}")

    # The sync time can be marked after it ran because all group syncs
    # are run in full, not polling for changes.
    # If this changes, we need to update this function.
    cc_pair.last_time_external_group_sync = datetime.now(timezone.utc)
    db_session.commit()


def mark_ccpair_with_indexing_trigger(
    cc_pair_id: int, indexing_mode: IndexingMode | None, db_session: Session
) -> None:
    """indexing_mode sets a field which will be picked up by a background task
    to trigger indexing. Set to None to disable the trigger."""
    try:
        cc_pair = db_session.execute(
            select(ConnectorCredentialPair)
            .where(ConnectorCredentialPair.id == cc_pair_id)
            .with_for_update()
        ).scalar_one()

        if cc_pair is None:
            raise ValueError(f"No cc_pair with ID: {cc_pair_id}")

        cc_pair.indexing_trigger = indexing_mode
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def get_kg_enabled_connectors(db_session: Session) -> list[KGConnectorData]:
    """
    Retrieves a list of connector IDs that have not been KG processed for a given tenant.
    Args:
        db_session (Session): The database session to use
    Returns:
        list[KGConnectorData]: List of connector IDs with KG extraction enabled but have unprocessed documents
    """
    try:
        stmt = select(Connector.id, Connector.source, Connector.kg_coverage_days).where(
            Connector.kg_processing_enabled
        )
        result = db_session.execute(stmt)

        connector_results = [
            KGConnectorData(id=row[0], source=row[1].lower(), kg_coverage_days=row[2])
            for row in result.fetchall()
        ]

        return connector_results

    except Exception as e:
        logger.error(f"Error fetching unprocessed connector IDs: {str(e)}")
        raise e
