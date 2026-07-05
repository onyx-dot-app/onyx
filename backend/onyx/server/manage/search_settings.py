from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.context.search.models import SavedSearchSettings
from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.connector_credential_pair import (
    fetch_indexable_standard_connector_credential_pair_ids,
)
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.connector_credential_pair import resync_cc_pair
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import SwitchoverType
from onyx.db.index_attempt import create_synthetic_seed_attempt
from onyx.db.index_attempt import expire_index_attempts
from onyx.db.llm import fetch_default_contextual_rag_model
from onyx.db.llm import update_default_contextual_model
from onyx.db.llm import update_no_default_contextual_rag_provider
from onyx.db.models import IndexModelStatus
from onyx.db.models import User
from onyx.db.port_attempt import cancel_active_port_attempts
from onyx.db.port_attempt import port_backfill_has_pending_work
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import delete_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_embedding_provider_from_provider_type
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.search_settings import update_current_search_settings
from onyx.db.search_settings import update_search_settings_status
from onyx.document_index.factory import get_all_document_indices
from onyx.document_index.factory import get_default_document_index
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.unstructured import delete_unstructured_api_key
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import update_unstructured_api_key
from onyx.natural_language_processing.search_nlp_models import clean_model_name
from onyx.server.manage.embedding.models import SearchSettingsDeleteRequest
from onyx.server.manage.models import FullModelVersionResponse
from onyx.server.models import IdReturn
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.configs import MULTI_TENANT

router = APIRouter(prefix="/search-settings")
logger = setup_logger()


@router.post("/set-new-search-settings", dependencies=[Depends(require_vector_db)])
def set_new_search_settings(
    search_settings_new: SearchSettingsCreationRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IdReturn:
    """
    Creates a new SearchSettings row and cancels the previous secondary indexing
    if any exists.
    """
    if search_settings_new.index_name:
        logger.warning("Index name was specified by request, this is not suggested")

    # Disallow contextual RAG for cloud deployments.
    if MULTI_TENANT and search_settings_new.enable_contextual_rag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contextual RAG disabled in Onyx Cloud",
        )

    # Validate cloud provider exists or create new LiteLLM provider.
    if search_settings_new.provider_type is not None:
        cloud_provider = get_embedding_provider_from_provider_type(
            db_session, provider_type=search_settings_new.provider_type
        )

        if cloud_provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No embedding provider exists for cloud embedding type {search_settings_new.provider_type}",
            )

    validate_contextual_rag_model(
        model_configuration_id=search_settings_new.contextual_rag_model_configuration_id,
        db_session=db_session,
        enable_contextual_rag=search_settings_new.enable_contextual_rag,
    )

    search_settings = get_current_search_settings(db_session)

    # An INSTANT backfill targets the PRESENT (not a secondary), so a new reindex would
    # abandon it — live index left short its un-ported docs, PAST source stuck
    # undeletable. Block until it drains (same condition _resolve_port_target_settings
    # uses).
    if (
        search_settings.use_port_flow
        and search_settings.port_backfill_source_id is not None
        and port_backfill_has_pending_work(db_session, search_settings.id)
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "An INSTANT reindex is still backfilling the live index; wait for it to "
            "finish before starting another reindex.",
        )

    if search_settings_new.index_name is None:
        # We define index name here.
        index_name = f"danswer_chunk_{clean_model_name(search_settings_new.model_name)}"
        if (
            search_settings_new.model_name == search_settings.model_name
            and not search_settings.index_name.endswith(ALT_INDEX_SUFFIX)
        ):
            index_name += ALT_INDEX_SUFFIX
        search_values = search_settings_new.model_dump()
        search_values["index_name"] = index_name
        new_search_settings_request = SavedSearchSettings(**search_values)
    else:
        new_search_settings_request = SavedSearchSettings(
            **search_settings_new.model_dump()
        )

    secondary_search_settings = get_secondary_search_settings(db_session)

    if secondary_search_settings:
        # Cancel any background indexing jobs.
        expire_index_attempts(
            search_settings_id=secondary_search_settings.id, db_session=db_session
        )

        # Mark previous model as a past model directly.
        update_search_settings_status(
            search_settings=secondary_search_settings,
            new_status=IndexModelStatus.PAST,
            db_session=db_session,
        )

        # Cancel in-flight reindex ports for the superseded FUTURE. After the PAST
        # flip so check_for_port (which only targets the current secondary) won't
        # enqueue a replacement; the running port task stops at its next batch
        # boundary once it sees CANCELED.
        cancel_active_port_attempts(
            db_session, search_settings_id=secondary_search_settings.id
        )

    # Every new FUTURE reindexes via the port flow (re-embed PRESENT -> FUTURE in
    # place, no connector re-fetch). commit=False here and below so the FUTURE and
    # its seeds commit together: a FUTURE visible before its seeds makes workers
    # re-scan from scratch instead of resuming from PRESENT's poll cursor.
    new_search_settings = create_search_settings(
        search_settings=new_search_settings_request,
        db_session=db_session,
        use_port_flow=True,
        commit=False,
    )

    # Ensure the document indices have the new index immediately.
    document_indices = get_all_document_indices(search_settings, new_search_settings)
    for document_index in document_indices:
        # Pair instances already know about their secondary search settings via
        # the factory; only the primary embedding info needs to be passed in.
        document_index.verify_and_create_index_if_necessary(
            embedding_dim=search_settings.final_embedding_dim,
            embedding_precision=search_settings.embedding_precision,
        )

    # Pause index attempts for the currently in-use index to preserve resources.
    if DISABLE_INDEX_UPDATE_ON_SWAP:
        expire_index_attempts(
            search_settings_id=search_settings.id,
            db_session=db_session,
            commit=False,
        )
        for cc_pair in get_connector_credential_pairs(db_session):
            resync_cc_pair(
                cc_pair=cc_pair,
                search_settings_id=new_search_settings.id,
                db_session=db_session,
                commit=False,
            )

    # Seed the poll cursor: a synthetic SUCCESS IndexAttempt per in-scope cc_pair
    # carrying PRESENT's cursor, so the promoted settings resume instead of re-scanning
    # full history. INSTANT needs it too — it promotes immediately, so no seed means a
    # full re-fetch. Seed exactly the cc_pairs the port will copy — the SAME scope helper
    # the swap uses (excludes INVALID/DELETING; ACTIVE_ONLY further restricts to active).
    # Seeding one the port skips leaves its backlog uncopied while the cursor claims
    # "already ported" -> permanent recall loss once that connector is fixed.
    if new_search_settings.use_port_flow:
        active_only = new_search_settings.switchover_type == SwitchoverType.ACTIVE_ONLY
        portable_cc_pair_ids = set(
            fetch_indexable_standard_connector_credential_pair_ids(
                db_session, active_cc_pairs_only=active_only
            )
        )
        for cc_pair in get_connector_credential_pairs(db_session):
            if cc_pair.id not in portable_cc_pair_ids:
                continue
            indexing_start = cc_pair.connector.indexing_start
            earliest_index = indexing_start.timestamp() if indexing_start else 0.0
            poll_range_end = get_last_successful_attempt_poll_range_end(
                cc_pair.id, earliest_index, search_settings, db_session
            )
            create_synthetic_seed_attempt(
                connector_credential_pair_id=cc_pair.id,
                search_settings_id=new_search_settings.id,
                db_session=db_session,
                poll_range_end=poll_range_end,
            )

    # Atomic: FUTURE row and its seeds become visible together.
    db_session.commit()
    return IdReturn(id=new_search_settings.id)


@router.post("/cancel-new-embedding", dependencies=[Depends(require_vector_db)])
def cancel_new_embedding(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    secondary_search_settings = get_secondary_search_settings(db_session)

    if secondary_search_settings:
        expire_index_attempts(
            search_settings_id=secondary_search_settings.id, db_session=db_session
        )

        update_search_settings_status(
            search_settings=secondary_search_settings,
            new_status=IndexModelStatus.PAST,
            db_session=db_session,
        )

        # Stop any in-flight reindex port for the canceled FUTURE; the running
        # task stops at its next batch boundary once it sees CANCELED.
        cancel_active_port_attempts(
            db_session, search_settings_id=secondary_search_settings.id
        )

        # remove the old index from the vector db
        primary_search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(
            primary_search_settings, None, db_session
        )
        document_index.verify_and_create_index_if_necessary(
            embedding_dim=primary_search_settings.final_embedding_dim,
            embedding_precision=primary_search_settings.embedding_precision,
        )


@router.delete("/delete-search-settings")
def delete_search_settings_endpoint(
    deletion_request: SearchSettingsDeleteRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        delete_search_settings(
            db_session=db_session,
            search_settings_id=deletion_request.search_settings_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/get-current-search-settings")
def get_current_search_settings_endpoint(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SavedSearchSettings:
    current_search_settings = get_current_search_settings(db_session)
    return SavedSearchSettings.from_db_model(current_search_settings)


@router.get("/get-secondary-search-settings")
def get_secondary_search_settings_endpoint(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SavedSearchSettings | None:
    secondary_search_settings = get_secondary_search_settings(db_session)
    if not secondary_search_settings:
        return None

    return SavedSearchSettings.from_db_model(secondary_search_settings)


@router.get("/get-all-search-settings")
def get_all_search_settings(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FullModelVersionResponse:
    current_search_settings = get_current_search_settings(db_session)
    secondary_search_settings = get_secondary_search_settings(db_session)
    return FullModelVersionResponse(
        current_settings=SavedSearchSettings.from_db_model(current_search_settings),
        secondary_settings=(
            SavedSearchSettings.from_db_model(secondary_search_settings)
            if secondary_search_settings
            else None
        ),
    )


# Updates current non-reindex search settings
@router.post("/update-inference-settings")
def update_saved_search_settings(
    search_settings: SavedSearchSettings,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    # Disallow contextual RAG for cloud deployments
    if MULTI_TENANT and search_settings.enable_contextual_rag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contextual RAG disabled in Onyx Cloud",
        )

    # enable_contextual_rag is preserved here (never written), so don't validate it:
    # the flag is discarded, and validating would 400 a change we ignore.
    validate_contextual_rag_model(
        model_configuration_id=search_settings.contextual_rag_model_configuration_id,
        db_session=db_session,
    )

    update_current_search_settings(
        search_settings=search_settings, db_session=db_session
    )

    logger.info(
        "Updated current search settings to %s", search_settings.model_dump_json()
    )

    # Re-sync default to match PRESENT search settings
    _sync_default_contextual_model(db_session)


@router.get("/unstructured-api-key-set")
def unstructured_api_key_set(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> bool:
    api_key = get_unstructured_api_key()
    return api_key is not None


@router.put("/upsert-unstructured-api-key")
def upsert_unstructured_api_key(
    unstructured_api_key: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    update_unstructured_api_key(unstructured_api_key)


@router.delete("/delete-unstructured-api-key")
def delete_unstructured_api_key_endpoint(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    delete_unstructured_api_key()


def validate_contextual_rag_model(
    model_configuration_id: int | None,
    db_session: Session,
    enable_contextual_rag: bool = False,
) -> None:
    if model_configuration_id is None:
        if (
            enable_contextual_rag
            and fetch_default_contextual_rag_model(db_session) is None
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Contextual Retrieval is enabled but no Contextual Retrieval "
                "model is configured, and no tenant default exists.",
            )
        return
    from onyx.db.models import ModelConfiguration

    if not db_session.get(ModelConfiguration, model_configuration_id):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"model_configuration id={model_configuration_id} not found",
        )


def _sync_default_contextual_model(db_session: Session) -> None:
    """Syncs the default CONTEXTUAL_RAG flow to match the PRESENT search settings."""
    primary = get_current_search_settings(db_session)

    try:
        update_default_contextual_model(
            db_session=db_session,
            enable_contextual_rag=primary.enable_contextual_rag,
            model_configuration_id=primary.contextual_rag_model_configuration_id,
        )
    except ValueError as e:
        logger.error(
            "Error syncing default contextual model, defaulting to no contextual model: %s",
            e,
        )
        update_no_default_contextual_rag_provider(
            db_session=db_session,
        )
