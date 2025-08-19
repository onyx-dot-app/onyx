import time

from sqlalchemy.orm import Session

from onyx.configs.app_configs import VESPA_NUM_ATTEMPTS_ON_STARTUP
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import resync_cc_pair
from onyx.db.document import delete_all_documents_for_connector_credential_pair
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import cancel_indexing_attempts_for_search_settings
from onyx.db.index_attempt import (
    count_unique_cc_pairs_with_successful_index_attempts,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import SearchSettings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.search_settings import update_search_settings_status
from onyx.document_index.factory import get_default_document_index
from onyx.key_value_store.factory import get_kv_store
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _perform_index_swap(
    db_session: Session,
    current_search_settings: SearchSettings,
    secondary_search_settings: SearchSettings,
    all_cc_pairs: list[ConnectorCredentialPair],
    cleanup_documents: bool = False,
) -> None:
    """Swap the indices and expire the old one."""
    if len(all_cc_pairs) > 0:
        kv_store = get_kv_store()
        kv_store.store(KV_REINDEX_KEY, False)

        # Expire jobs for the now past index/embedding model
        cancel_indexing_attempts_for_search_settings(
            search_settings_id=current_search_settings.id,
            db_session=db_session,
        )

        # Recount aggregates
        for cc_pair in all_cc_pairs:
            resync_cc_pair(
                cc_pair=cc_pair,
                # sync based on the new search settings
                search_settings_id=secondary_search_settings.id,
                db_session=db_session,
            )

        if cleanup_documents:
            # clean up all DocumentByConnectorCredentialPair / Document rows, since we're
            # doing an instant swap and no documents will exist in the new index.
            for cc_pair in all_cc_pairs:
                delete_all_documents_for_connector_credential_pair(
                    db_session=db_session,
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                )

    # swap over search settings
    update_search_settings_status(
        search_settings=current_search_settings,
        new_status=IndexModelStatus.PAST,
        db_session=db_session,
    )
    update_search_settings_status(
        search_settings=secondary_search_settings,
        new_status=IndexModelStatus.PRESENT,
        db_session=db_session,
    )

    # remove the old index from the vector db
    document_index = get_default_document_index(secondary_search_settings, None)

    WAIT_SECONDS = 5

    success = False
    for x in range(VESPA_NUM_ATTEMPTS_ON_STARTUP):
        try:
            logger.notice(
                f"Vespa index swap (attempt {x+1}/{VESPA_NUM_ATTEMPTS_ON_STARTUP})..."
            )
            document_index.ensure_indices_exist(
                primary_embedding_dim=secondary_search_settings.final_embedding_dim,
                primary_embedding_precision=secondary_search_settings.embedding_precision,
                # just finished swap, no more secondary index
                secondary_index_embedding_dim=None,
                secondary_index_embedding_precision=None,
            )

            logger.notice("Vespa index swap complete.")
            success = True
            break
        except Exception:
            logger.exception(
                f"Vespa index swap did not succeed. The Vespa service may not be ready yet. Retrying in {WAIT_SECONDS} seconds."
            )
            time.sleep(WAIT_SECONDS)

    if not success:
        logger.error(
            f"Vespa index swap did not succeed. Attempt limit reached. ({VESPA_NUM_ATTEMPTS_ON_STARTUP})"
        )

    return


def check_and_perform_index_swap(db_session: Session) -> SearchSettings | None:
    """Get count of cc-pairs and count of successful index_attempts for the
    new model grouped by connector + credential, if it's the same, then assume
    new index is done building. If so, swap the indices and expire the old one.

    Returns None if search settings did not change, or the old search settings if they
    did change.
    """
    # Default CC-pair created for Ingestion API unused here
    all_cc_pairs = get_connector_credential_pairs(db_session, include_user_files=True)
    cc_pair_count = max(len(all_cc_pairs) - 1, 0)
    secondary_search_settings = get_secondary_search_settings(db_session)

    if not secondary_search_settings:
        return None

    # If the secondary search settings are not configured to reindex in the background,
    # we can just swap over instantly
    if not secondary_search_settings.background_reindex_enabled:
        current_search_settings = get_current_search_settings(db_session)
        _perform_index_swap(
            db_session=db_session,
            current_search_settings=current_search_settings,
            secondary_search_settings=secondary_search_settings,
            all_cc_pairs=all_cc_pairs,
            # clean up all DocumentByConnectorCredentialPair / Document rows, since we're
            # doing an instant swap.
            cleanup_documents=True,
        )
        return current_search_settings

    unique_cc_indexings = count_unique_cc_pairs_with_successful_index_attempts(
        search_settings_id=secondary_search_settings.id, db_session=db_session
    )

    # Index Attempts are cleaned up as well when the cc-pair is deleted so the logic in this
    # function is correct. The unique_cc_indexings are specifically for the existing cc-pairs
    old_search_settings = None
    if unique_cc_indexings > cc_pair_count:
        logger.error("More unique indexings than cc pairs, should not occur")

    if cc_pair_count == 0 or cc_pair_count == unique_cc_indexings:
        # Swap indices
        current_search_settings = get_current_search_settings(db_session)
        _perform_index_swap(
            db_session=db_session,
            current_search_settings=current_search_settings,
            secondary_search_settings=secondary_search_settings,
            all_cc_pairs=all_cc_pairs,
        )
        old_search_settings = current_search_settings

    return old_search_settings
