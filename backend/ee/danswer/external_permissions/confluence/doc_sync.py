from typing import Any

from sqlalchemy.orm import Session

from danswer.db.models import ConnectorCredentialPair
from danswer.utils.logger import setup_logger


logger = setup_logger()


def confluence_doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    docs_with_additional_info: dict[str, Any],
    sync_details: dict[str, Any],
) -> None:
    logger.debug("Not yet implemented ACL sync for confluence, no-op")
