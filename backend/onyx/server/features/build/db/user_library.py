"""Database operations for User Library (CRAFT_FILE connector).

Handles storage quota queries and connector/credential setup for the
User Library feature in Craft.
"""

from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import Integer
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.connector import fetch_connectors
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.connector_credential_pair import (
    get_connector_credential_pairs_for_user,
)
from onyx.db.credentials import create_credential
from onyx.db.credentials import fetch_credentials_for_user
from onyx.db.enums import AccessType
from onyx.db.enums import ProcessingMode
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.features.build.configs import USER_LIBRARY_CONNECTOR_NAME
from onyx.server.features.build.configs import USER_LIBRARY_CREDENTIAL_NAME
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_user_storage_bytes(db_session: Session, user_id: UUID) -> int:
    """Get total storage usage for a user's library files.

    Uses SQL aggregation to sum file_size from doc_metadata JSONB for all
    CRAFT_FILE documents owned by this user, avoiding loading all documents
    into Python memory.
    """
    stmt = (
        select(
            func.coalesce(
                func.sum(
                    cast(
                        DbDocument.doc_metadata["file_size"].as_string(),
                        Integer,
                    )
                ),
                0,
            )
        )
        .join(
            DocumentByConnectorCredentialPair,
            DbDocument.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .join(
            Connector,
            ConnectorCredentialPair.connector_id == Connector.id,
        )
        .where(Connector.source == DocumentSource.CRAFT_FILE)
        .where(ConnectorCredentialPair.creator_id == user_id)
        .where(DbDocument.doc_metadata["is_directory"].as_boolean().is_not(True))
    )
    result = db_session.execute(stmt).scalar()
    return int(result or 0)


def get_or_create_craft_connector(db_session: Session, user: User) -> tuple[int, int]:
    """Get or create the CRAFT_FILE connector for a user.

    Returns:
        Tuple of (connector_id, credential_id)

    Note: We need to create a credential even though CRAFT_FILE doesn't require
    authentication. This is because Onyx's connector-credential pair system
    requires a credential for all connectors. The credential is empty ({}).

    This function handles recovery from partial creation failures by detecting
    orphaned connectors (connectors without cc_pairs) and completing their setup.
    """
    # Check if user already has a complete CRAFT_FILE cc_pair
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        eager_load_credential=True,
        processing_mode=ProcessingMode.RAW_BINARY,
    )

    for cc_pair in cc_pairs:
        if (
            cc_pair.connector.source == DocumentSource.CRAFT_FILE
            and cc_pair.creator_id == user.id
        ):
            return cc_pair.connector.id, cc_pair.credential.id

    # No cc_pair for this user — find or create the shared CRAFT_FILE connector
    existing_connectors = fetch_connectors(
        db_session, sources=[DocumentSource.CRAFT_FILE]
    )
    connector_id: int | None = None
    for conn in existing_connectors:
        if conn.name == USER_LIBRARY_CONNECTOR_NAME:
            connector_id = conn.id
            break

    if connector_id is None:
        connector_data = ConnectorBase(
            name=USER_LIBRARY_CONNECTOR_NAME,
            source=DocumentSource.CRAFT_FILE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={"disabled_paths": []},
            refresh_freq=None,
            prune_freq=None,
        )
        connector_response = create_connector(
            db_session=db_session,
            connector_data=connector_data,
        )
        connector_id = connector_response.id

    # Try to reuse an existing User Library credential for this user
    existing_credentials = fetch_credentials_for_user(
        db_session=db_session,
        user=user,
    )
    credential = None
    for cred in existing_credentials:
        if (
            cred.source == DocumentSource.CRAFT_FILE
            and cred.name == USER_LIBRARY_CREDENTIAL_NAME
        ):
            credential = cred
            break

    if credential is None:
        credential_data = CredentialBase(
            credential_json={},
            admin_public=False,
            source=DocumentSource.CRAFT_FILE,
            name=USER_LIBRARY_CREDENTIAL_NAME,
        )
        credential = create_credential(
            credential_data=credential_data,
            user=user,
            db_session=db_session,
        )

    # Link them with RAW_BINARY processing mode
    add_credential_to_connector(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential.id,
        user=user,
        cc_pair_name=USER_LIBRARY_CONNECTOR_NAME,
        access_type=AccessType.PRIVATE,
        groups=None,
        processing_mode=ProcessingMode.RAW_BINARY,
    )

    db_session.commit()
    return connector_id, credential.id
