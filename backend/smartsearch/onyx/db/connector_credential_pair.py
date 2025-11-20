from sqlalchemy import delete
from sqlalchemy.orm import Session
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

def _delete_connector_credential_pair_user_groups_relationship__no_commit(
    db_session: Session, connector_id: int, credential_id: int
) -> None:
    # Retrieve the specified connector-credential association from the database
    association_record = get_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
    )
    # Verify that the association exists; otherwise, signal an error condition
    if association_record is None:
        raise ValueError(
            f"No matching ConnectorCredentialPair exists for connector_id: {connector_id} "
            f"and credential_id: {credential_id}"
        )
    # Prepare a deletion statement targeting the relationship table
    # using the association's unique identifier
    removal_query = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == association_record.id
    )
    # Apply the deletion operation within the session
    db_session.execute(removal_query)

def get_cc_pairs_by_source(
    db_session: Session,
    source_type: DocumentSource,
    access_type: AccessType | None = None,
    status: ConnectorCredentialPairStatus | None = None,
) -> list[ConnectorCredentialPair]:
    """
    Retrieves a collection of ConnectorCredentialPair instances associated with a specific
    document source category. Supports additional refinement based on access permissions
    and operational status if provided. The output is arranged in ascending order of
    the pair's internal identifier.
    """
    # Initialize the core query by linking the pair to its connector and applying the source constraint
    base_query = db_session.query(ConnectorCredentialPair).join(
        ConnectorCredentialPair.connector
    ).filter(
        Connector.source == source_type
    ).order_by(
        ConnectorCredentialPair.id
    )
    # Conditionally incorporate access type filter to narrow results
    if access_type is not None:
        base_query = base_query.filter(ConnectorCredentialPair.access_type == access_type)
    # Conditionally incorporate status filter for further precision
    if status is not None:
        base_query = base_query.filter(ConnectorCredentialPair.status == status)
    # Execute the query and collect all matching records
    matching_pairs = base_query.all()
    return matching_pairs

def get_all_auto_sync_cc_pairs(
    db_session: Session,
) -> list[ConnectorCredentialPair]:
    # Construct and run a query to fetch all pairs configured for automatic synchronization
    sync_pairs_query = (
        db_session.query(ConnectorCredentialPair).filter(
            ConnectorCredentialPair.access_type == AccessType.SYNC
        )
    )
    return sync_pairs_query.all()
