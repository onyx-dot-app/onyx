from sqlalchemy import or_
from sqlalchemy import select

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import Connector
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.kg.models import KGStage
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_unprocessed_connector_ids(tenant_id: str) -> list[int]:
    """
    Retrieves a list of connector IDs that have not been KG processed for a given tenant.

    Args:
        tenant_id (str): The ID of the tenant to check for unprocessed connectors

    Returns:
        list[int]: List of connector IDs that have enabled KG extraction but have unprocessed documents
    """
    try:
        with get_session_with_current_tenant() as db_session:
            # Find connectors that:
            # 1. Have KG extraction enabled
            # 2. Have documents that haven't been KG processed
            stmt = (
                select(Connector.id)
                .distinct()
                .join(DocumentByConnectorCredentialPair)
                .where(
                    Connector.kg_processing_enabled,
                    or_(
                        DocumentByConnectorCredentialPair.kg_stage
                        == KGStage.EXTRACTION_READY,
                        DocumentByConnectorCredentialPair.kg_stage is None,
                    ),
                )
            )

            result = db_session.execute(stmt)
            return [row[0] for row in result.fetchall()]

    except Exception as e:
        logger.error(f"Error fetching unprocessed connector IDs: {str(e)}")
        return []
