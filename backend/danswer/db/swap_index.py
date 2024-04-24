from sqlalchemy.orm import Session

from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.connector_credential_pair import resync_cc_pair
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.embedding_model import get_secondary_db_embedding_model
from danswer.db.embedding_model import update_embedding_model_status
from danswer.db.enums import IndexModelStatus
from danswer.db.index_attempt import cancel_indexing_attempts_past_model
from danswer.db.index_attempt import (
    count_unique_cc_pairs_with_successful_index_attempts,
)
from danswer.utils.logger import setup_logger

logger = setup_logger()


def check_index_swap(db_session: Session) -> None:
    """Get count of cc-pairs and count of successful index_attempts for the
    new model grouped by connector + credential, if it's the same, then assume
    new index is done building. If so, swap the indices and expire the old one."""
    # Default CC-pair created for Ingestion API unused here
    all_cc_pairs = get_connector_credential_pairs(db_session)
    cc_pair_count = max(len(all_cc_pairs) - 1, 0)
    embedding_model = get_secondary_db_embedding_model(db_session)

    if not embedding_model:
        return

    unique_cc_indexings = count_unique_cc_pairs_with_successful_index_attempts(
        embedding_model_id=embedding_model.id, db_session=db_session
    )

    # Index Attempts are cleaned up as well when the cc-pair is deleted so the logic in this
    # function is correct. The unique_cc_indexings are specifically for the existing cc-pairs
    if unique_cc_indexings > cc_pair_count:
        logger.error("More unique indexings than cc pairs, should not occur")

    if cc_pair_count == 0 or cc_pair_count == unique_cc_indexings:
        # Swap indices
        now_old_embedding_model = get_current_db_embedding_model(db_session)
        update_embedding_model_status(
            embedding_model=now_old_embedding_model,
            new_status=IndexModelStatus.PAST,
            db_session=db_session,
        )

        update_embedding_model_status(
            embedding_model=embedding_model,
            new_status=IndexModelStatus.PRESENT,
            db_session=db_session,
        )

        if cc_pair_count > 0:
            # Expire jobs for the now past index/embedding model
            cancel_indexing_attempts_past_model(db_session)

            # Recount aggregates
            for cc_pair in all_cc_pairs:
                resync_cc_pair(cc_pair, db_session=db_session)
