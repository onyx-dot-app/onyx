from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.background.celery.tasks.index_reclaim.tasks import enqueue_index_reclaim
from onyx.background.celery.tasks.port.tasks import (
    PortResumeResult,
    resume_paused_port_unit,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import (
    DISABLE_INDEX_UPDATE_ON_SWAP,
    ENABLE_OPENSEARCH_INDEXING_FOR_ONYX,
    OLD_INDEX_RECLAIM_ENABLED,
)
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
from onyx.db.enums import (
    IndexReclaimStatus,
    Permission,
    SwitchoverType,
    VectorQuantization,
)
from onyx.db.index_attempt import create_synthetic_seed_attempt, expire_index_attempts
from onyx.db.llm import (
    fetch_default_contextual_rag_model,
    update_default_contextual_model,
    update_no_default_contextual_rag_provider,
)
from onyx.db.models import (
    CloudEmbeddingProvider,
    IndexModelStatus,
    SearchSettings,
    User,
)
from onyx.db.port_attempt import (
    ReindexErrorRow,
    ReindexProgressCounts,
    cancel_active_port_attempts,
    get_reindex_error_rows,
    get_reindex_progress_counts,
    has_active_port_attempts,
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
    mark_abandoned_future_for_reclaim__no_commit,
    set_reclaim_intent_on_current__no_commit,
    update_current_search_settings,
    update_search_settings_status,
)
from onyx.document_index.factory import (
    get_all_document_indices,
    get_default_document_index,
)
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.constants import LUCENE_SCALAR_QUANTIZATION
from onyx.document_index.opensearch.index_reclaim import (
    ReclaimOutcome,
    reclaim_index_data,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.unstructured import (
    delete_unstructured_api_key,
    get_unstructured_api_key,
    update_unstructured_api_key,
)
from onyx.natural_language_processing.search_nlp_models import (
    EmbeddingModel,
    clean_model_name,
)
from onyx.server.manage.embedding.models import SearchSettingsDeleteRequest
from onyx.server.manage.models import (
    FullModelVersionResponse,
    UnstructuredApiKeyRequest,
)
from onyx.server.models import IdReturn
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import (
    ALT_INDEX_SUFFIX,
    MODEL_SERVER_HOST,
    MODEL_SERVER_PORT,
    MULTI_TENANT,
)
from shared_configs.contextvars import get_current_tenant_id
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    EmbeddingModelStatus,
    find_embedding_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType

router = APIRouter(prefix="/search-settings")
logger = setup_logger()


@router.post("/set-new-search-settings", dependencies=[Depends(require_vector_db)])
def set_new_search_settings(
    search_settings_new: SearchSettingsCreationRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IdReturn:
    """Create the new SearchSettings row that the port flow re-embeds into.

    Only one re-index runs at a time. This raises CONFLICT instead of superseding an
    existing one: either a secondary FUTURE is already in flight, or an INSTANT
    switchover is still backfilling the live index. Cancel the running re-index first.

    Embedding models only move forward: legacy models are refused as a new target,
    except for a re-index with the PRESENT model (see _check_embedding_model_target).
    """
    if search_settings_new.index_name:
        logger.warning("Index name was specified by request, this is not suggested")

    # Disallow contextual RAG for cloud deployments.
    if MULTI_TENANT and search_settings_new.enable_contextual_rag:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Contextual RAG disabled in Onyx Cloud"
        )

    # Validate cloud provider exists or create new LiteLLM provider.
    cloud_provider: CloudEmbeddingProvider | None = None
    if search_settings_new.provider_type is not None:
        cloud_provider = get_embedding_provider_from_provider_type(
            db_session, provider_type=search_settings_new.provider_type
        )

        if cloud_provider is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"No embedding provider exists for cloud embedding type {search_settings_new.provider_type}",
            )

    validate_contextual_rag_model(
        model_configuration_id=search_settings_new.contextual_rag_model_configuration_id,
        db_session=db_session,
        enable_contextual_rag=search_settings_new.enable_contextual_rag,
    )
    _validate_vector_quantization_supported(search_settings_new.vector_quantization)

    # Before the PRESENT row lock below: the probe is a network call that can take
    # minutes against a slow provider.
    cloud_target_probed = cloud_provider is not None and _probe_cloud_target_unlocked(
        db_session, search_settings_new, cloud_provider
    )

    # Lock PRESENT so concurrent reindex submissions serialize: without it two racers both
    # pass the no-FUTURE guard below and the loser trips the FUTURE unique index (raw 500).
    search_settings = get_current_search_settings(db_session, for_update=True)

    # An INSTANT backfill targets the PRESENT (not a secondary), so a new reindex would
    # abandon it — live index left short its un-ported docs, PAST source stuck
    # undeletable. Block until it drains (same condition _resolve_port_target_settings
    # uses).
    if _instant_backfill_pending(db_session, search_settings):
        raise OnyxError(OnyxErrorCode.CONFLICT, _INSTANT_BACKFILL_PENDING_MESSAGE)

    # One re-index at a time: refuse a new one while a secondary FUTURE is still in flight
    # (no supersede). Reuse of a retired index's name is handled by _guard_index_name_reuse.
    if get_secondary_search_settings(db_session) is not None:
        raise OnyxError(OnyxErrorCode.CONFLICT, _REINDEX_IN_PROGRESS_MESSAGE)

    # Upgrade-only: a new target must be the PRESENT model or a selectable model.
    # Runs before anything below writes or commits.
    target_check = _check_embedding_model_target(
        search_settings_new,
        present_provider_type=search_settings.provider_type,
        present_model_name=search_settings.model_name,
        present_model_dim=search_settings.model_dim,
        present_reduced_dimension=search_settings.reduced_dimension,
    )
    search_settings_new = target_check.request
    if (
        target_check.needs_cloud_probe
        and not cloud_target_probed
        and cloud_provider is not None
    ):
        # Only when PRESENT changed after the unlocked read. Rare enough that
        # probing under the lock is acceptable.
        _probe_cloud_embedding_model(search_settings_new, cloud_provider)

    if search_settings_new.index_name is None:
        search_values = search_settings_new.model_dump()
        search_values["index_name"] = _compute_index_name(
            search_settings_new, search_settings
        )
        new_search_settings_request = SavedSearchSettings(**search_values)
    else:
        new_search_settings_request = SavedSearchSettings(
            **search_settings_new.model_dump()
        )

    # An explicit index_name can still name the live index, and the port would then write
    # this generation's chunks into the index serving search.
    if new_search_settings_request.index_name == search_settings.index_name:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "The new index would take the name of the one currently serving search. "
            "Check the embedding model name, or set an explicit index name.",
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

    # Written here so it commits together with the new FUTURE below; a failure in
    # between would otherwise leave the live index marked for reclaim with no FUTURE.
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


_INSTANT_BACKFILL_PENDING_MESSAGE = (
    "An INSTANT reindex is still backfilling the live index; wait for it to "
    "finish before starting another reindex."
)
_REINDEX_IN_PROGRESS_MESSAGE = (
    "A re-index is already in progress. Cancel it before starting a new one."
)


def _instant_backfill_pending(db_session: Session, present: SearchSettings) -> bool:
    return (
        present.use_port_flow
        and present.port_backfill_source_id is not None
        and port_backfill_has_pending_work(db_session, present.id)
    )


# Providers whose model list Onyx owns. Only SELECTABLE registry models are valid
# new targets for them. LiteLLM and Azure take free-form names, so they stay open.
_REGISTRY_ONLY_CLOUD_PROVIDERS = frozenset(
    {
        EmbeddingProvider.OPENAI,
        EmbeddingProvider.COHERE,
        EmbeddingProvider.GOOGLE,
        EmbeddingProvider.VOYAGE,
    }
)

# Texts embedded by the pre-flight probe of a new cloud model.
_CLOUD_PROBE_PASSAGES = [
    "Onyx connects to the documents of a company and answers questions about them.",
    "An embedding model turns each chunk of text into a vector for semantic search.",
]
_CLOUD_PROBE_QUERY = "Which component turns text into vectors?"
_CLOUD_PROBE_MAX_ERROR_CHARS = 1000


class _EmbeddingModelTargetCheck(BaseModel):
    """Result of the upgrade-only rules for one set-new-search-settings request."""

    # The request to continue with. A selectable model has its canonical name.
    request: SearchSettingsCreationRequest
    # True for a new selectable cloud model, which the probe embeds before the
    # FUTURE is created.
    needs_cloud_probe: bool


def _embedding_model_match_key(
    provider_type: EmbeddingProvider | None, model_name: str
) -> tuple[EmbeddingProvider | None, str]:
    """The fold that names indexes, so case and punctuation variants match."""
    return provider_type, clean_model_name(model_name.strip())


def _embedding_provider_label(provider_type: EmbeddingProvider | None) -> str:
    return provider_type.value if provider_type is not None else "self-hosted"


def _describe_embedding_model(
    provider_type: EmbeddingProvider | None, model_name: str
) -> str:
    return f"'{model_name}' ({_embedding_provider_label(provider_type)})"


def _selectable_embedding_models_hint() -> str:
    names_by_provider: dict[str, list[str]] = {}
    for spec in selectable_embedding_model_specs():
        names_by_provider.setdefault(
            _embedding_provider_label(spec.provider_type), []
        ).append(spec.model_name)
    return "; ".join(
        f"{provider_label}: {', '.join(names)}"
        for provider_label, names in names_by_provider.items()
    )


def _not_selectable_error(
    request: SearchSettingsCreationRequest, spec: EmbeddingModelSpec | None
) -> OnyxError:
    model = _describe_embedding_model(request.provider_type, request.model_name)
    if spec is not None:
        reason = (
            f"{model} is a legacy embedding model. Existing indexes on it keep "
            "working, but it can't be chosen for a new index."
        )
    else:
        reason = f"{model} is not an embedding model that Onyx supports."
    return OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"{reason} Choose one of these models: {_selectable_embedding_models_hint()}. "
        "A re-index with the current model is still allowed.",
    )


def _validate_selectable_embedding_request(
    request: SearchSettingsCreationRequest, spec: EmbeddingModelSpec
) -> None:
    """A selectable model must use the registry's settings: the index and the
    embedding code depend on them."""
    problems: list[str] = []
    if request.model_dim != spec.model_dim:
        problems.append(f"model_dim must be {spec.model_dim}, not {request.model_dim}")
    if request.normalize != spec.normalize:
        problems.append(f"normalize must be {spec.normalize}")
    if (request.query_prefix or "") != spec.query_prefix:
        problems.append(f"query_prefix must be {spec.query_prefix!r}")
    if (request.passage_prefix or "") != spec.passage_prefix:
        problems.append(f"passage_prefix must be {spec.passage_prefix!r}")
    if request.reduced_dimension is not None:
        if MULTI_TENANT:
            problems.append("reduced_dimension is not supported in Onyx Cloud")
        elif not spec.supports_reduced_dimension:
            problems.append("this model does not support reduced_dimension")
        elif not 0 < request.reduced_dimension < spec.model_dim:
            problems.append(
                f"reduced_dimension must be between 1 and {spec.model_dim - 1}"
            )
    if problems:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Invalid settings for embedding model '{spec.model_name}': "
            f"{'; '.join(problems)}.",
        )


def _check_embedding_model_target(
    request: SearchSettingsCreationRequest,
    *,
    present_provider_type: EmbeddingProvider | None,
    present_model_name: str,
    present_model_dim: int,
    present_reduced_dimension: int | None,
) -> _EmbeddingModelTargetCheck:
    """Upgrade-only rules for a new embedding target, applied in order:

    1. Same model as PRESENT: allow. This is a re-index to change quantization,
       contextual RAG or switchover, legacy models included. Stored rows often
       differ from the registry (e.g. empty prefixes), so they are not compared
       to it. Only the dimension is checked: model_dim must be PRESENT's (or the
       registry's, to move a custom row to the registry model), and in
       MULTI_TENANT reduced_dimension must be PRESENT's, because tenants share
       the index. A variant of a selectable model's name gets the canonical name:
       the model server and the tokenizer match it exactly.
    2. A SELECTABLE registry model: allow, with the canonical name and the
       registry's settings.
    3. Any other model of a provider whose list Onyx owns: reject.
    4. A LEGACY self-hosted model: reject.
    5. Anything else (custom HF models, LiteLLM, Azure): allow.

    Raises OnyxError(INVALID_INPUT) when a rule rejects the target."""
    spec = find_embedding_model_spec(request.provider_type, request.model_name)
    selectable_spec = (
        spec
        if spec is not None and spec.status == EmbeddingModelStatus.SELECTABLE
        else None
    )

    # Rule 1
    request_key = _embedding_model_match_key(request.provider_type, request.model_name)
    if request_key == _embedding_model_match_key(
        present_provider_type, present_model_name
    ):
        allowed_dims = {present_model_dim}
        if selectable_spec is not None:
            allowed_dims.add(selectable_spec.model_dim)
        if request.model_dim not in allowed_dims:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"A re-index with the current model must keep its dimension: "
                f"model_dim must be {' or '.join(str(d) for d in sorted(allowed_dims))}, "
                f"not {request.model_dim}.",
            )
        if MULTI_TENANT and request.reduced_dimension != present_reduced_dimension:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "reduced_dimension can't be changed in Onyx Cloud: "
                "all tenants on a model share its index.",
            )
        if selectable_spec is not None:
            request = request.model_copy(
                update={"model_name": selectable_spec.model_name}
            )
        return _EmbeddingModelTargetCheck(request=request, needs_cloud_probe=False)

    # Rule 2
    if selectable_spec is not None:
        _validate_selectable_embedding_request(request, selectable_spec)
        return _EmbeddingModelTargetCheck(
            request=request.model_copy(
                update={"model_name": selectable_spec.model_name}
            ),
            needs_cloud_probe=selectable_spec.provider_type is not None,
        )

    # Rule 3
    if request.provider_type in _REGISTRY_ONLY_CLOUD_PROVIDERS:
        raise _not_selectable_error(request, spec)

    # Rule 4: any spec left here is LEGACY.
    if request.provider_type is None and spec is not None:
        raise _not_selectable_error(request, spec)

    # Rule 5
    return _EmbeddingModelTargetCheck(request=request, needs_cloud_probe=False)


def _probe_cloud_target_unlocked(
    db_session: Session,
    request: SearchSettingsCreationRequest,
    cloud_provider: CloudEmbeddingProvider,
) -> bool:
    """Probe a new selectable cloud target before PRESENT is locked. Returns True
    if the probe ran and passed.

    Reads PRESENT without the lock. A CONFLICT or a rejection is left to the
    checks under the lock, so the probe never runs for a request that they
    refuse. If PRESENT or the re-index state changes before the lock, the check
    under the lock probes instead."""
    spec = find_embedding_model_spec(request.provider_type, request.model_name)
    if spec is None or spec.status != EmbeddingModelStatus.SELECTABLE:
        return False

    present = get_current_search_settings(db_session)
    present_provider_type = present.provider_type
    present_model_name = present.model_name
    present_model_dim = present.model_dim
    present_reduced_dimension = present.reduced_dimension
    conflict_visible = (
        _instant_backfill_pending(db_session, present)
        or get_secondary_search_settings(db_session) is not None
    )
    # The locked read must load PRESENT again, not reuse this unlocked copy.
    db_session.expire(present)
    if conflict_visible:
        return False

    try:
        target_check = _check_embedding_model_target(
            request,
            present_provider_type=present_provider_type,
            present_model_name=present_model_name,
            present_model_dim=present_model_dim,
            present_reduced_dimension=present_reduced_dimension,
        )
    except OnyxError:
        return False
    if not target_check.needs_cloud_probe:
        return False

    # Nothing is written yet. End the read transaction so that the connection is
    # not idle in a transaction during the network calls, which can take
    # minutes. The session has expire_on_commit=False, so cloud_provider stays
    # loaded and the probe makes no query.
    db_session.commit()
    _probe_cloud_embedding_model(target_check.request, cloud_provider)
    return True


def _probe_cloud_embedding_model(
    request: SearchSettingsCreationRequest,
    cloud_provider: CloudEmbeddingProvider,
) -> None:
    """Embed a few texts with the exact target cloud model and the stored
    credentials, so a key without access, a wrong region or a wrong dimension
    fails now and not in the middle of the re-index.

    Raises OnyxError(INVALID_INPUT) with the provider's error on failure."""
    provider_type = request.provider_type
    if provider_type is None:
        raise ValueError("The cloud embedding probe needs a cloud provider type")
    expected_dim = request.reduced_dimension or request.model_dim
    model = _describe_embedding_model(provider_type, request.model_name)

    embedding_model = EmbeddingModel(
        # Not used: cloud models bypass the model server.
        server_host=MODEL_SERVER_HOST,
        server_port=MODEL_SERVER_PORT,
        model_name=request.model_name,
        normalize=request.normalize,
        query_prefix=request.query_prefix,
        passage_prefix=request.passage_prefix,
        api_key=(
            cloud_provider.api_key.get_value(apply_mask=False)
            if cloud_provider.api_key is not None
            else None
        ),
        api_url=cloud_provider.api_url,
        provider_type=provider_type,
        api_version=cloud_provider.api_version,
        deployment_name=cloud_provider.deployment_name,
        reduced_dimension=request.reduced_dimension,
    )
    try:
        passage_embeddings = embedding_model.encode(
            _CLOUD_PROBE_PASSAGES, text_type=EmbedTextType.PASSAGE
        )
        query_embeddings = embedding_model.encode(
            [_CLOUD_PROBE_QUERY], text_type=EmbedTextType.QUERY
        )
    except Exception as e:
        logger.warning("Embedding probe of %s failed: %s", model, e)
        hint = "Check that the API key has access to this model."
        if provider_type == EmbeddingProvider.GOOGLE:
            hint += (
                " Vertex AI serves gemini-embedding-2 only in the global, us and eu "
                "locations. Onyx takes the location from the 'location' field of the "
                "service account JSON, then GOOGLE_CLOUD_LOCATION, then 'global'."
            )
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Onyx could not embed test text with {model}: "
            f"{str(e)[:_CLOUD_PROBE_MAX_ERROR_CHARS]} {hint}",
        )

    if (
        len(passage_embeddings) != len(_CLOUD_PROBE_PASSAGES)
        or len(query_embeddings) != 1
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{model} returned {len(passage_embeddings)} passage and "
            f"{len(query_embeddings)} query vectors for "
            f"{len(_CLOUD_PROBE_PASSAGES)} passages and 1 query.",
        )
    wrong_dims = sorted(
        {
            len(embedding)
            for embedding in passage_embeddings + query_embeddings
            if len(embedding) != expected_dim
        }
    )
    if wrong_dims:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{model} returned vectors of size "
            f"{', '.join(str(dim) for dim in wrong_dims)}, but the new index "
            f"expects size {expected_dim}.",
        )


def _validate_vector_quantization_supported(
    vector_quantization: VectorQuantization,
) -> None:
    """Rejects a quantization level that the OpenSearch cluster cannot index.

    Runs before anything is written, so an older external cluster gets a clear
    error instead of a failed index creation. A cluster that does not report
    its OpenSearch version is not checked.
    """
    lucene_scalar_quantization = LUCENE_SCALAR_QUANTIZATION.get(vector_quantization)
    if lucene_scalar_quantization is None or not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        return
    with OpenSearchClient() as opensearch_client:
        cluster_version = opensearch_client.get_opensearch_version()
    min_version = lucene_scalar_quantization.min_opensearch_version
    if cluster_version is not None and cluster_version < min_version:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"The {vector_quantization.value} vector quantization needs OpenSearch "
            f"{min_version[0]}.{min_version[1]} or later. This cluster runs "
            f"OpenSearch {cluster_version[0]}.{cluster_version[1]}.",
        )


def _compute_index_name(
    requested: SearchSettingsCreationRequest, present: SearchSettings
) -> str:
    """The index name a new FUTURE takes when the caller doesn't supply one.

    The suffix keys on the cleaned names, not the raw ones: clean_model_name lowercases and
    folds "/", "-" and "." together, so "intfloat/E5-Base" and "intfloat/e5-base" reduce to
    one index name. Comparing raw would skip the suffix for those and hand the new FUTURE
    the live index's own name, leaving the port writing into the index serving search."""
    index_name = f"danswer_chunk_{clean_model_name(requested.model_name)}"
    if clean_model_name(requested.model_name) == clean_model_name(
        present.model_name
    ) and not present.index_name.endswith(ALT_INDEX_SUFFIX):
        index_name += ALT_INDEX_SUFFIX
    return index_name


def _guard_index_name_reuse(db_session: Session, index_name: str) -> None:
    """Refuse a reindex whose new index_name still holds a PAST generation's data (reusing
    it would adopt that data), and pull the occupant into the reclaim cycle so it drains
    without a manual delete — this is what reclaims legacy NULL / stalled / BLOCKED rows on
    demand. Mark each skip-soak DELETING, kick its reclaim, then raise so the caller retries
    once the name is free."""
    occupants = find_unreclaimed_past_by_index_name(db_session, index_name)
    if not occupants:
        return
    if not OLD_INDEX_RECLAIM_ENABLED:
        # Reclaim is off (the run task no-ops), so don't strand these as DELETING that will
        # never drain — just refuse; an operator re-enables reclaim or removes the index.
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "An index of the same name from an earlier re-index still holds data, and "
            "reclamation is disabled. Re-enable reclamation or remove that index first.",
        )
    for occupant in occupants:
        mark_abandoned_future_for_reclaim__no_commit(occupant)
    db_session.commit()
    tenant_id = get_current_tenant_id()
    for occupant in occupants:
        enqueue_index_reclaim(client_app, tenant_id, occupant.id)
    raise OnyxError(
        OnyxErrorCode.INDEX_NAME_RECLAIMING,
        "An index of the same name from an earlier re-index still holds data; it's being "
        "cleaned up now. Start the re-index again in a moment.",
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


def _reclaim_abandoned_future(
    db_session: Session, abandoned_future: SearchSettings, present: SearchSettings
) -> None:
    """Reclaim an abandoned (reverted/superseded) FUTURE's index — its partial-port data
    would otherwise block a later same-name reindex via the name-reuse guard. Marks the
    row for the reclaim loop; single-tenant additionally drops the index inline so retry
    works immediately, independent of the reclaim kill switch (MT shares the physical
    index across tenants, so its per-tenant slice is left to the loop). Caller commits."""
    # Checked before marking: marking hands the row to the reclaim loop, which deletes
    # whatever index_name it carries, so skipping only the inline drop below saves nothing.
    if abandoned_future.index_name == present.index_name:
        logger.error(
            "Abandoned FUTURE %s names the live index %s; leaving it for an operator "
            "rather than handing it to the reclaim loop.",
            abandoned_future.id,
            abandoned_future.index_name,
        )
        return

    mark_abandoned_future_for_reclaim__no_commit(abandoned_future)
    # Don't drop the index while a canceled port task may still be writing to it; leave the
    # row DELETING for the reclaim loop.
    if has_active_port_attempts(db_session, abandoned_future.id):
        return
    # MT shares the physical index across tenants, so leave its slice to the loop.
    if MULTI_TENANT:
        return
    try:
        if (
            reclaim_index_data(
                abandoned_future.index_name,
                TenantState(
                    tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT
                ),
            )
            == ReclaimOutcome.COMPLETE
        ):
            abandoned_future.reclaim_status = IndexReclaimStatus.RECLAIMED
    except Exception:
        logger.exception(
            "Inline reclaim of abandoned FUTURE index %s failed; leaving it for the "
            "reclaim loop",
            abandoned_future.index_name,
        )


@router.post("/cancel-new-embedding", dependencies=[Depends(require_vector_db)])
def cancel_new_embedding(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    secondary_search_settings = get_secondary_search_settings(db_session)

    if secondary_search_settings is None:
        # No secondary FUTURE to cancel. An INSTANT switchover already promoted the new
        # model to PRESENT and backfills it in place, so there is nothing to revert to —
        # surface that instead of silently succeeding (the UI would show a false "canceled").
        if _active_port_settings(db_session) is not None:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "The new embedding model is already live (INSTANT switchover); an "
                "in-progress reindex-port backfill can no longer be reverted.",
            )
        return

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

    primary_search_settings = get_current_search_settings(db_session)

    # The reverted FUTURE index holds abandoned partial-port data — reclaim it so a later
    # same-model reindex isn't blocked by the name-reuse guard.
    reverted_settings_id = secondary_search_settings.id
    _reclaim_abandoned_future(
        db_session, secondary_search_settings, primary_search_settings
    )

    # Clear the intent this cancellation's own reindex stamped, so a later swap can't act
    # on a stale consent set. Locked first, so a reindex submitted in between is either
    # already visible below or waits for this commit.
    get_current_search_settings(db_session, for_update=True)
    a_newer_reindex_owns_the_intent = (
        get_secondary_search_settings(db_session) is not None
    )
    if not a_newer_reindex_owns_the_intent:
        clear_reclaim_intent__no_commit(db_session, primary_search_settings.id)
    db_session.commit()

    document_index = get_default_document_index(
        primary_search_settings, None, db_session
    )
    document_index.verify_and_create_index_if_necessary(
        embedding_dim=primary_search_settings.final_embedding_dim,
    )

    # Kick off reclamation now instead of waiting for the reclaim beat. Safe no-op if the
    # row is already RECLAIMED (single-tenant inline drop above) or reclaim is disabled.
    enqueue_index_reclaim(client_app, get_current_tenant_id(), reverted_settings_id)


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
    request: UnstructuredApiKeyRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    update_unstructured_api_key(request.unstructured_api_key)


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
