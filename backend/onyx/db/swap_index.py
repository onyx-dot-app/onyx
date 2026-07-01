import time

from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.app_configs import VESPA_NUM_ATTEMPTS_ON_STARTUP
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.db.connector_credential_pair import (
    fetch_indexable_standard_connector_credential_pair_ids,
)
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import resync_cc_pair
from onyx.db.document import count_secondary_only_sync_pending_documents_for_cc_pairs
from onyx.db.document import delete_all_documents_for_connector_credential_pair
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import SwitchoverType
from onyx.db.index_attempt import cancel_indexing_attempts_for_search_settings
from onyx.db.index_attempt import (
    count_unique_active_cc_pairs_with_successful_index_attempts,
)
from onyx.db.index_attempt import count_unique_cc_pairs_with_successful_index_attempts
from onyx.db.llm import update_default_contextual_model
from onyx.db.llm import update_no_default_contextual_rag_provider
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import cancel_active_port_attempts
from onyx.db.port_attempt import get_active_port_attempt
from onyx.db.port_attempt import get_latest_port_attempt
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.search_settings import update_search_settings_status
from onyx.document_index.factory import get_all_document_indices
from onyx.key_value_store.factory import get_kv_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _perform_index_swap(
    db_session: Session,
    new_search_settings: SearchSettings,
    all_cc_pairs: list[ConnectorCredentialPair],
    cleanup_documents: bool = False,
) -> SearchSettings | None:
    """Swap the indices and expire the old one.

    Returns the old search settings if the swap was successful, otherwise None.
    """
    current_search_settings = get_current_search_settings(db_session)
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
                search_settings_id=new_search_settings.id,
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

    # Record the index being promoted-from so the INSTANT post-swap port keeps
    # reading it once it becomes PAST. Only INSTANT backfills after the swap; setting
    # this for a non-INSTANT swap wrongly keeps the old index un-deletable, since a
    # lingering FAILED port row keeps is_active_port_backfill_source True forever.
    if (
        new_search_settings.use_port_flow
        and new_search_settings.switchover_type == SwitchoverType.INSTANT
    ):
        new_search_settings.port_backfill_source_id = current_search_settings.id

    # swap over search settings
    update_search_settings_status(
        search_settings=current_search_settings,
        new_status=IndexModelStatus.PAST,
        db_session=db_session,
    )
    update_search_settings_status(
        search_settings=new_search_settings,
        new_status=IndexModelStatus.PRESENT,
        db_session=db_session,
    )

    # FUTURE is now live: cancel stragglers that dropped out of the required set
    # (paused/INVALID) so they stop writing into the live index. Skip for INSTANT —
    # there the swap is deliberately mid-port and the ports keep backfilling.
    if (
        new_search_settings.use_port_flow
        and new_search_settings.switchover_type != SwitchoverType.INSTANT
    ):
        cancel_active_port_attempts(
            db_session,
            new_search_settings.id,
            reason="Canceled: FUTURE promoted by index swap",
        )

    # Update the default contextual model to match the newly promoted settings
    try:
        update_default_contextual_model(
            db_session=db_session,
            enable_contextual_rag=new_search_settings.enable_contextual_rag,
            model_configuration_id=new_search_settings.contextual_rag_model_configuration_id,
        )
    except ValueError as e:
        logger.error("Model not found, defaulting to no contextual model: %s", e)
        update_no_default_contextual_rag_provider(
            db_session=db_session,
        )
        new_search_settings.enable_contextual_rag = False
        new_search_settings.contextual_rag_model_configuration_id = None
        db_session.commit()

    # This flow is for checking and possibly creating an index so we get all
    # indices.
    document_indices = get_all_document_indices(new_search_settings, None, None)

    WAIT_SECONDS = 5

    for document_index in document_indices:
        success = False
        for x in range(VESPA_NUM_ATTEMPTS_ON_STARTUP):
            try:
                logger.notice(
                    "Document index %s swap (attempt %s/%s)...",
                    document_index.__class__.__name__,
                    x + 1,
                    VESPA_NUM_ATTEMPTS_ON_STARTUP,
                )
                document_index.verify_and_create_index_if_necessary(
                    embedding_dim=new_search_settings.final_embedding_dim,
                    embedding_precision=new_search_settings.embedding_precision,
                )

                logger.notice("Document index swap complete.")
                success = True
                break
            except Exception:
                logger.exception(
                    "Document index swap for %s did not succeed. The document index services may not be ready yet. Retrying in %s seconds.",
                    document_index.__class__.__name__,
                    WAIT_SECONDS,
                )
                time.sleep(WAIT_SECONDS)

        if not success:
            logger.error(
                "Document index swap for %s did not succeed. Attempt limit reached. (%s)",
                document_index.__class__.__name__,
                VESPA_NUM_ATTEMPTS_ON_STARTUP,
            )
            return None

    return current_search_settings


def _required_cc_pairs_for_switchover(
    db_session: Session,
    all_cc_pairs: list[ConnectorCredentialPair],
    switchover_type: SwitchoverType,
) -> list[ConnectorCredentialPair]:
    """The cc_pairs whose port must finish before a port-flow swap.

    Scoped through the SAME helper check_for_port uses, so the gated set stays a
    subset of what the watchdog ports — gating on a cc_pair it never ports (e.g.
    INVALID, excluded by indexable_statuses()) would deadlock the swap. ACTIVE_ONLY
    restricts to active statuses; other modes also include PAUSED. The Ingestion
    pair is kept in: check_for_port ports it too, so its port must gate the swap.
    """
    portable_ids = set(
        fetch_indexable_standard_connector_credential_pair_ids(
            db_session,
            active_cc_pairs_only=(switchover_type == SwitchoverType.ACTIVE_ONLY),
        )
    )
    return [cc_pair for cc_pair in all_cc_pairs if cc_pair.id in portable_ids]


def _port_swap_ready(
    db_session: Session,
    new_search_settings: SearchSettings,
    required_cc_pairs: list[ConnectorCredentialPair],
) -> bool:
    """Port-flow swap gate: True once every required cc_pair's port is SUCCESS (none
    active) and its deferred metadata-sync backlog has drained. The port copy is the
    whole bar — no post-port connector index attempt. The drain is scoped to
    required_cc_pairs: a global count would deadlock on un-portable INVALID/DELETING
    docs that never reach FUTURE."""
    ss_id = new_search_settings.id
    for cc_pair in required_cc_pairs:
        if get_active_port_attempt(db_session, cc_pair.id, ss_id) is not None:
            return False
        latest_port = get_latest_port_attempt(db_session, cc_pair.id, ss_id)
        if latest_port is None or not latest_port.status.is_successful():
            return False

    return (
        count_secondary_only_sync_pending_documents_for_cc_pairs(
            db_session, [cc_pair.id for cc_pair in required_cc_pairs]
        )
        == 0
    )


def check_and_perform_index_swap(db_session: Session) -> SearchSettings | None:
    """Get count of cc-pairs and count of successful index_attempts for the
    new model grouped by connector + credential, if it's the same, then assume
    new index is done building. If so, swap the indices and expire the old one.

    Returns None if search settings did not change, or the old search settings if they
    did change.
    """
    if DISABLE_VECTOR_DB:
        return None

    # Default CC-pair created for Ingestion API unused here
    all_cc_pairs = get_connector_credential_pairs(db_session)
    cc_pair_count = max(len(all_cc_pairs) - 1, 0)
    new_search_settings = get_secondary_search_settings(db_session)

    if not new_search_settings:
        return None

    # Handle switchover based on switchover_type
    switchover_type = new_search_settings.switchover_type

    # Port-flow FUTURE: swap on the port-aware criterion, not the legacy
    # successful-index count (a broken connector must not block the swap).
    if new_search_settings.use_port_flow:
        if switchover_type == SwitchoverType.INSTANT:
            # Swap now and let the port keep backfilling old data into the now-live
            # index in the background — no wait, and no wipe (the port populates it,
            # so cleanup_documents would destroy live data).
            return _perform_index_swap(
                db_session=db_session,
                new_search_settings=new_search_settings,
                all_cc_pairs=all_cc_pairs,
            )
        required_cc_pairs = _required_cc_pairs_for_switchover(
            db_session, all_cc_pairs, switchover_type
        )
        if not required_cc_pairs or _port_swap_ready(
            db_session, new_search_settings, required_cc_pairs
        ):
            return _perform_index_swap(
                db_session=db_session,
                new_search_settings=new_search_settings,
                all_cc_pairs=all_cc_pairs,
            )
        return None

    # INSTANT: Swap immediately without waiting
    if switchover_type == SwitchoverType.INSTANT:
        return _perform_index_swap(
            db_session=db_session,
            new_search_settings=new_search_settings,
            all_cc_pairs=all_cc_pairs,
            # clean up all DocumentByConnectorCredentialPair / Document rows, since we're
            # doing an instant swap.
            cleanup_documents=True,
        )

    # REINDEX: Wait for all connectors to complete
    elif switchover_type == SwitchoverType.REINDEX:
        unique_cc_indexings = count_unique_cc_pairs_with_successful_index_attempts(
            search_settings_id=new_search_settings.id, db_session=db_session
        )

        # Index Attempts are cleaned up as well when the cc-pair is deleted so the logic in this
        # function is correct. The unique_cc_indexings are specifically for the existing cc-pairs
        if unique_cc_indexings > cc_pair_count:
            logger.error("More unique indexings than cc pairs, should not occur")

        if cc_pair_count == 0 or cc_pair_count == unique_cc_indexings:
            # Swap indices
            return _perform_index_swap(
                db_session=db_session,
                new_search_settings=new_search_settings,
                all_cc_pairs=all_cc_pairs,
            )

        return None

    # ACTIVE_ONLY: Wait for only non-paused connectors to complete
    elif switchover_type == SwitchoverType.ACTIVE_ONLY:
        # Count non-paused cc_pairs (excluding the default Ingestion API cc_pair)
        active_cc_pairs = [
            cc_pair
            for cc_pair in all_cc_pairs
            if cc_pair.status != ConnectorCredentialPairStatus.PAUSED
        ]
        active_cc_pair_count = max(len(active_cc_pairs) - 1, 0)

        unique_active_cc_indexings = (
            count_unique_active_cc_pairs_with_successful_index_attempts(
                search_settings_id=new_search_settings.id, db_session=db_session
            )
        )

        if unique_active_cc_indexings > active_cc_pair_count:
            logger.error(
                "More unique active indexings than active cc pairs, should not occur"
            )

        if (
            active_cc_pair_count == 0
            or active_cc_pair_count == unique_active_cc_indexings
        ):
            # Swap indices
            return _perform_index_swap(
                db_session=db_session,
                new_search_settings=new_search_settings,
                all_cc_pairs=all_cc_pairs,
            )

        return None

    # Should not reach here, but handle gracefully
    logger.error("Unknown switchover_type: %s", switchover_type)
    return None
