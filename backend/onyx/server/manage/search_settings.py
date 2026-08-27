from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.background.celery.tasks.port.tasks import (
    PortResumeResult,
    resume_paused_port_unit,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.context.search.models import (
    ContextualRagModelUpdateResponse,
    SavedSearchSettings,
    SearchSettingsCreationRequest,
)
from onyx.db.connector_credential_pair import (
    compute_wont_port_cc_pair_ids,
    fetch_indexable_standard_connector_credential_pair_ids,
    get_connector_credential_pairs,
    get_last_successful_attempt_poll_range_end,
    resync_cc_pair,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, SwitchoverType
from onyx.db.index_attempt import create_synthetic_seed_attempt, expire_index_attempts
from onyx.db.llm import (
    fetch_default_contextual_rag_model,
    update_default_contextual_model,
    update_no_default_contextual_rag_provider,
)
from onyx.db.models import IndexModelStatus, SearchSettings, User
from onyx.db.port_attempt import (
    ReindexErrorRow,
    ReindexProgressCounts,
    cancel_active_port_attempts,
    get_reindex_error_rows,
    get_reindex_progress_counts,
    port_backfill_has_pending_work,
)
from onyx.db.search_settings import (
    clear_reclaim_intent__no_commit,
    create_search_settings,
    delete_search_settings,
    find_unreclaimed_past_by_index_name,
    get_current_search_settings,
    get_embedding_provider_from_provider_type,
    get_secondary_search_settings,
    set_reclaim_intent_on_current__no_commit,
    update_current_search_settings,
    update_search_settings_status,
)
from onyx.document_index.factory import (
    get_all_document_indices,
    get_default_document_index,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.unstructured import (
    delete_unstructured_api_key,
    get_unstructured_api_key,
    update_unstructured_api_key,
)
from onyx.natural_language_processing.search_nlp_models import clean_model_name
from onyx.server.manage.embedding.models import SearchSettingsDeleteRequest
from onyx.server.manage.models import FullModelVersionResponse
from onyx.server.models import IdReturn
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX, MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

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

    # ALT_INDEX_SUFFIX alternation can make this FUTURE's index_name equal a PAST's whose
    # data isn't reclaimed yet. Refuse before verify_and_create_index_if_necessary below
    # adopts that same-named index and inherits its stale data.
    if new_search_settings_request.index_name is not None:
        _guard_index_name_reuse(db_session, new_search_settings_request.index_name)

    # Resolve before the block below starts committing, so rejecting a stale consent set
    # cannot first tear down the reindex this one supersedes.
    consented_deletions = _resolve_reclaim_intent(
        db_session,
        search_settings_new.switchover_type,
        search_settings_new.acknowledged_wont_port_cc_pair_ids,
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

    # Must stay below the calls above that commit. Written any earlier, a later failure
    # leaves the live index marked for reclaim with no FUTURE ever created.
    set_reclaim_intent_on_current__no_commit(db_session, consented_deletions)

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

    # Atomic: FUTURE row, its seeds, and the reclaim intent become visible together.
    db_session.commit()
    return IdReturn(id=new_search_settings.id)


def _guard_index_name_reuse(db_session: Session, index_name: str) -> None:
    if find_unreclaimed_past_by_index_name(db_session, index_name):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "An index of the same name from an earlier reindex still holds data. Wait "
            "for reclamation to finish before starting this reindex.",
        )


def _resolve_reclaim_intent(
    db_session: Session,
    switchover_type: SwitchoverType,
    acknowledged_wont_port_cc_pair_ids: list[int] | None,
) -> list[int]:
    """Raises when consent is missing or stale, so the request fails before the reindex
    has committed anything."""
    return _resolve_consented_deletions(
        acknowledged_wont_port_cc_pair_ids,
        compute_wont_port_cc_pair_ids(db_session, switchover_type),
    )


def _resolve_consented_deletions(
    acknowledged: list[int] | None, server_wont_port: list[int]
) -> list[int]:
    """The cc_pairs the post-swap reclaim may delete.

    Missing consent raises rather than proceeding, because the old index is reclaimed
    either way: a caller let through would leave a PAST row that nothing collects and the
    name-reuse guard never releases, blocking the next reindex of that model. A stale
    acknowledgment raises too, so a connector that became paused or invalid after the page
    loaded is never deleted unseen. Drift the other way, where a consented connector went
    active again, just deletes less."""
    if not server_wont_port:
        return []
    if acknowledged is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Some connectors won't be carried into the new index. Acknowledge the ones "
            "whose data you agree to delete before starting the reindex.",
        )
    unacknowledged = set(server_wont_port) - set(acknowledged)
    if unacknowledged:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "The set of connectors that won't be re-indexed changed since you opened "
            "this page (one or more became paused or invalid). Reload and review the "
            "deletion list before starting the reindex.",
        )
    return server_wont_port


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

        # The canceled reindex stamped reclaim intent on this PRESENT (the would-be PAST);
        # clear it so a later swap can't act on a stale consent set. No-op if unset.
        clear_reclaim_intent__no_commit(db_session, primary_search_settings.id)
        db_session.commit()

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


def _active_port_settings(db_session: Session) -> SearchSettings | None:
    secondary = get_secondary_search_settings(db_session)
    if secondary is not None and secondary.use_port_flow:
        return secondary
    present = get_current_search_settings(db_session)
    if (
        present.use_port_flow
        and present.port_backfill_source_id is not None
        and port_backfill_has_pending_work(db_session, present.id)
    ):
        return present
    return None


@router.get("/reindex-progress")
def get_reindex_progress(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ReindexProgressCounts:
    target = _active_port_settings(db_session)
    if target is None:
        return ReindexProgressCounts(
            total=0, waiting=0, in_progress=0, completed=0, failed=0, paused=0
        )
    return get_reindex_progress_counts(db_session, target.id)


@router.get("/reindex-errors")
def get_reindex_errors(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ReindexErrorRow]:
    target = _active_port_settings(db_session)
    if target is None:
        return []
    return get_reindex_error_rows(db_session, target.id)


class PortActionRequest(BaseModel):
    """Resume one paused port unit — exactly one scope set."""

    cc_pair_id: int | None = None
    user_id: UUID | None = None


class PortActionResponse(BaseModel):
    ok: bool


@router.post("/reindex/port/resume")
def resume_paused_port(
    request: PortActionRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PortActionResponse:
    if (request.cc_pair_id is None) == (request.user_id is None):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Exactly one of cc_pair_id / user_id must be set.",
        )
    target = _active_port_settings(db_session)
    if target is None:
        raise OnyxError(OnyxErrorCode.CONFLICT, "No reindex port is currently active.")
    result = resume_paused_port_unit(
        client_app,
        get_current_tenant_id(),
        request.cc_pair_id,
        request.user_id,
        target.id,
    )
    if result is PortResumeResult.NOT_PAUSED:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "That unit is not paused (it may have already been resumed or is still "
            "retrying).",
        )
    if result is PortResumeResult.DISPATCH_FAILED:
        # The unit WAS resumed (a fresh attempt is committed), but the task broker was
        # unavailable so it wasn't dispatched now. Don't report an immediate resume — the
        # scheduler re-enqueues it within a few minutes.
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "The unit was resumed but could not be dispatched right now (the task queue is "
            "unavailable). It will start automatically within a few minutes.",
        )
    return PortActionResponse(ok=True)


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


def _validate_contextual_model_only_update(
    current: SearchSettings,
    requested: SavedSearchSettings,
) -> int:
    model_configuration_id = requested.contextual_rag_model_configuration_id
    if model_configuration_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Select a Contextual Retrieval model.",
        )

    expected = SavedSearchSettings.from_db_model(current).model_copy(
        update={
            "contextual_rag_model_configuration_id": model_configuration_id,
        }
    )
    if requested != expected:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only the Contextual Retrieval model can be updated without re-indexing.",
        )
    return model_configuration_id


@router.post("/update-inference-settings")
def update_saved_search_settings(
    search_settings: SavedSearchSettings,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ContextualRagModelUpdateResponse:
    # Disallow contextual RAG for cloud deployments
    if MULTI_TENANT and search_settings.enable_contextual_rag:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Contextual RAG disabled in Onyx Cloud",
        )

    if (
        get_secondary_search_settings(db_session) is not None
        or _active_port_settings(db_session) is not None
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "A re-index is in progress. Wait for it to finish before updating the "
            "Contextual Retrieval model.",
        )

    current = get_current_search_settings(db_session)
    if not current.enable_contextual_rag:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Contextual Retrieval must be enabled before its model can be updated "
            "without re-indexing.",
        )

    model_configuration_id = _validate_contextual_model_only_update(
        current, search_settings
    )
    validate_contextual_rag_model(
        model_configuration_id=model_configuration_id,
        db_session=db_session,
        enable_contextual_rag=True,
    )

    previous_model_configuration_id = current.contextual_rag_model_configuration_id
    update_current_search_settings(
        search_settings=search_settings, db_session=db_session
    )
    _sync_default_contextual_model(db_session)

    logger.info(
        "Updated current contextual retrieval model from %s to %s",
        previous_model_configuration_id,
        model_configuration_id,
    )
    emit_audit_event(
        AuditAction.CONTEXTUAL_RAG_MODEL_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="search_settings",
        resource_id=current.id,
        extra={
            "previous_model_configuration_id": previous_model_configuration_id,
            "model_configuration_id": model_configuration_id,
        },
    )
    return ContextualRagModelUpdateResponse(
        contextual_rag_model_configuration_id=model_configuration_id
    )


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
