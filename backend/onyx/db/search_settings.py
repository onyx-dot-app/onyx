from sqlalchemy import and_, delete, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from onyx.configs.model_configs import (
    DEFAULT_DOCUMENT_ENCODER_MODEL,
    DOCUMENT_ENCODER_MODEL,
)
from onyx.context.search.models import SavedSearchSettings
from onyx.db.llm import fetch_embedding_provider
from onyx.db.models import (
    CloudEmbeddingProvider,
    IndexAttempt,
    IndexModelStatus,
    IndexReclaimStatus,
    SearchSettings,
)
from onyx.server.manage.embedding.models import (
    CloudEmbeddingProvider as ServerCloudEmbeddingProvider,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import PRESERVED_SEARCH_FIELDS
from shared_configs.enums import EmbeddingProvider

logger = setup_logger()

# search_settings columns that are NOT NULL but whose Pydantic source fields are
# typed str | None. Registry-less cloud providers (e.g. Bedrock/LiteLLM/Azure)
# can arrive without prefixes; coerce None -> "" to avoid a NotNullViolation.
_NOT_NULL_STR_FIELDS = {"query_prefix", "passage_prefix"}


class ActiveSearchSettings:
    primary: SearchSettings
    secondary: SearchSettings | None

    def __init__(
        self, primary: SearchSettings, secondary: SearchSettings | None
    ) -> None:
        self.primary = primary
        self.secondary = secondary


def create_search_settings(
    search_settings: SavedSearchSettings,
    db_session: Session,
    status: IndexModelStatus = IndexModelStatus.FUTURE,
    # Default used only when the saved model omits use_port_flow (None). The reindex
    # request never carries the flag (not a request field), so the endpoint opts in
    # via this param; an explicit value on the saved model wins (e.g. a round-trip).
    use_port_flow: bool = False,
    # False flushes instead of committing, so the caller can commit this row
    # atomically with its port seeds (a seedless FUTURE makes workers re-scan).
    commit: bool = True,
) -> SearchSettings:
    embedding_model = SearchSettings(
        model_name=search_settings.model_name,
        model_dim=search_settings.model_dim,
        normalize=search_settings.normalize,
        # See _NOT_NULL_STR_FIELDS: coerce None -> "" to avoid a NotNullViolation.
        query_prefix=search_settings.query_prefix or "",
        passage_prefix=search_settings.passage_prefix or "",
        status=status,
        index_name=search_settings.index_name,
        provider_type=search_settings.provider_type,
        multipass_indexing=search_settings.multipass_indexing,
        embedding_precision=search_settings.embedding_precision,
        reduced_dimension=search_settings.reduced_dimension,
        enable_contextual_rag=search_settings.enable_contextual_rag,
        contextual_rag_model_configuration_id=search_settings.contextual_rag_model_configuration_id,
        switchover_type=search_settings.switchover_type,
        use_port_flow=(
            search_settings.use_port_flow
            if search_settings.use_port_flow is not None
            else use_port_flow
        ),
    )

    db_session.add(embedding_model)
    if commit:
        db_session.commit()
    else:
        db_session.flush()  # populate id without committing

    return embedding_model


def get_embedding_provider_from_provider_type(
    db_session: Session, provider_type: EmbeddingProvider
) -> CloudEmbeddingProvider | None:
    query = select(CloudEmbeddingProvider).where(
        CloudEmbeddingProvider.provider_type == provider_type
    )
    provider = db_session.execute(query).scalars().first()
    return provider if provider else None


def get_current_db_embedding_provider(
    db_session: Session,
) -> ServerCloudEmbeddingProvider | None:
    search_settings = get_current_search_settings(db_session=db_session)

    if search_settings.provider_type is None:
        return None

    embedding_provider = fetch_embedding_provider(
        db_session=db_session,
        provider_type=search_settings.provider_type,
    )
    if embedding_provider is None:
        raise RuntimeError("No embedding provider exists for this model.")

    current_embedding_provider = ServerCloudEmbeddingProvider.from_request(
        cloud_provider_model=embedding_provider
    )

    return current_embedding_provider


def delete_search_settings(db_session: Session, search_settings_id: int) -> None:
    from onyx.db.port_attempt import is_active_port_backfill_source

    current_settings = get_current_search_settings(db_session)

    if current_settings.id == search_settings_id:
        raise ValueError("Cannot delete currently active search settings")

    # A promoted index may still be backfilling its port from this one; deleting it
    # would strand that port (SET NULL drops the source out from under it).
    if is_active_port_backfill_source(db_session, search_settings_id):
        raise ValueError(
            "Cannot delete search settings: a reindex port is still backfilling from it"
        )

    # First, delete associated index attempts
    index_attempts_query = delete(IndexAttempt).where(
        IndexAttempt.search_settings_id == search_settings_id
    )
    db_session.execute(index_attempts_query)

    # Then, delete the search settings
    search_settings_query = delete(SearchSettings).where(
        and_(
            SearchSettings.id == search_settings_id,
            SearchSettings.status != IndexModelStatus.PRESENT,
        )
    )

    db_session.execute(search_settings_query)
    db_session.commit()


def get_current_search_settings(db_session: Session) -> SearchSettings:
    query = (
        select(SearchSettings)
        .where(SearchSettings.status == IndexModelStatus.PRESENT)
        .order_by(SearchSettings.id.desc())
    )
    result = db_session.execute(query)
    latest_settings = result.scalars().first()

    if not latest_settings:
        raise RuntimeError("No search settings specified; DB is not in a valid state.")
    return latest_settings


def get_secondary_search_settings(db_session: Session) -> SearchSettings | None:
    query = (
        select(SearchSettings)
        .where(SearchSettings.status == IndexModelStatus.FUTURE)
        .order_by(SearchSettings.id.desc())
    )
    result = db_session.execute(query)
    latest_settings = result.scalars().first()

    return latest_settings


def get_search_settings_by_id(
    db_session: Session, search_settings_id: int
) -> SearchSettings | None:
    return db_session.get(SearchSettings, search_settings_id)


def active_secondary_port_target(db_session: Session) -> SearchSettings | None:
    """The secondary index a reindex-port is populating (the dual-write target), or None.
    Pure — never unpins a drained INSTANT source (unlike _resolve_port_target_settings).
    None after an INSTANT swap: FUTURE was promoted to current, so the live pass covers it."""
    secondary = get_secondary_search_settings(db_session)
    if secondary is not None and secondary.use_port_flow:
        return secondary
    return None


def get_active_search_settings(db_session: Session) -> ActiveSearchSettings:
    """Returns active search settings. Secondary search settings may be None."""

    # Get the primary and secondary search settings
    primary_search_settings = get_current_search_settings(db_session)
    secondary_search_settings = get_secondary_search_settings(db_session)
    return ActiveSearchSettings(
        primary=primary_search_settings, secondary=secondary_search_settings
    )


def get_active_search_settings_list(db_session: Session) -> list[SearchSettings]:
    """Returns active search settings as a list. Primary settings are the first element,
    and if secondary search settings exist, they will be the second element."""

    search_settings_list: list[SearchSettings] = []

    active_search_settings = get_active_search_settings(db_session)
    search_settings_list.append(active_search_settings.primary)
    if active_search_settings.secondary:
        search_settings_list.append(active_search_settings.secondary)

    return search_settings_list


def get_all_search_settings(db_session: Session) -> list[SearchSettings]:
    query = select(SearchSettings).order_by(SearchSettings.id.desc())
    result = db_session.execute(query)
    all_settings = result.scalars().all()
    return list(all_settings)


def update_search_settings(
    current_settings: SearchSettings,
    updated_settings: SavedSearchSettings,
    preserved_fields: list[str],
) -> None:
    mapped_columns = {c.key for c in sa_inspect(SearchSettings).mapper.columns}
    for field, value in updated_settings.model_dump().items():
        if field not in preserved_fields and field in mapped_columns:
            # A client that explicitly sends null for a NOT NULL prefix column
            # must not write NULL (NotNullViolation). See _NOT_NULL_STR_FIELDS.
            if value is None and field in _NOT_NULL_STR_FIELDS:
                value = ""
            setattr(current_settings, field, value)


def update_current_search_settings(
    db_session: Session,
    search_settings: SavedSearchSettings,
    preserved_fields: list[str] = PRESERVED_SEARCH_FIELDS,
) -> None:
    current_settings = get_current_search_settings(db_session)
    if not current_settings:
        logger.warning("No current search settings found to update")
        return

    update_search_settings(current_settings, search_settings, preserved_fields)
    db_session.commit()
    logger.info("Current search settings updated successfully")


def update_secondary_search_settings(
    db_session: Session,
    search_settings: SavedSearchSettings,
    preserved_fields: list[str] = PRESERVED_SEARCH_FIELDS,
) -> None:
    secondary_settings = get_secondary_search_settings(db_session)
    if not secondary_settings:
        logger.warning("No secondary search settings found to update")
        return

    preserved_fields = PRESERVED_SEARCH_FIELDS
    update_search_settings(secondary_settings, search_settings, preserved_fields)

    db_session.commit()
    logger.info("Secondary search settings updated successfully")


def update_search_settings_status(
    search_settings: SearchSettings, new_status: IndexModelStatus, db_session: Session
) -> None:
    search_settings.status = new_status
    db_session.commit()


def user_has_overridden_embedding_model() -> bool:
    return DOCUMENT_ENCODER_MODEL != DEFAULT_DOCUMENT_ENCODER_MODEL


# Old-index reclamation (post-reindex deletion of the now-PAST index).
# Reclaim lifecycle lives as columns on SearchSettings (see models.py). The mutation
# helpers only touch the row; the caller owns the commit. The reclaim beat task drives
# the state machine one step per tick.

# States the beat task still acts on. BLOCKED is parked (alerted) and excluded.
_ACTIONABLE_RECLAIM_STATUSES = [
    IndexReclaimStatus.PENDING,
    IndexReclaimStatus.SOAKING,
    IndexReclaimStatus.DELETING,
]

# States where the old index's data still physically exists (not yet reclaimed) —
# includes BLOCKED, whose deletion never completed. Only RECLAIMED means the data is
# gone. The name-reuse guard uses this to refuse reusing a still-dirty index name.
_INDEX_PRESENT_RECLAIM_STATUSES = [
    IndexReclaimStatus.PENDING,
    IndexReclaimStatus.SOAKING,
    IndexReclaimStatus.DELETING,
    IndexReclaimStatus.BLOCKED,
]


def set_reclaim_intent_on_current__no_commit(
    db_session: Session, consented_cc_pair_ids: list[int]
) -> None:
    """Mark the current PRESENT index (the future PAST) for reclamation at reindex
    submit. Stores the consented not-ported cc_pairs. No-op if there is no PRESENT.
    Caller commits (atomically with FUTURE creation)."""
    present = db_session.scalar(
        select(SearchSettings).where(SearchSettings.status == IndexModelStatus.PRESENT)
    )
    if present is None:
        return
    present.reclaim_status = IndexReclaimStatus.PENDING
    present.pending_cc_pair_deletions = consented_cc_pair_ids or None
    present.reclaim_attempts = 0
    present.reclaim_last_error = None


def clear_reclaim_intent__no_commit(
    db_session: Session, search_settings_id: int
) -> None:
    """Undo reclaim intent (e.g. reindex canceled before swap). Caller commits."""
    ss = db_session.get(SearchSettings, search_settings_id)
    if ss is None:
        return
    ss.reclaim_status = None
    ss.reclaim_stopped_reading_at = None
    ss.reclaim_attempts = 0
    ss.reclaim_last_error = None
    ss.pending_cc_pair_deletions = None


def fetch_reclaimable_past_settings(
    db_session: Session, limit: int
) -> list[SearchSettings]:
    """PAST indices still needing reclamation (PENDING/SOAKING/DELETING), oldest
    first, capped at `limit`. BLOCKED rows are excluded (parked + alerted)."""
    stmt = (
        select(SearchSettings)
        .where(
            SearchSettings.status == IndexModelStatus.PAST,
            SearchSettings.reclaim_status.in_(_ACTIONABLE_RECLAIM_STATUSES),
        )
        .order_by(SearchSettings.id)
        .limit(limit)
    )
    return list(db_session.scalars(stmt))


def advance_to_soaking__no_commit(search_settings: SearchSettings) -> bool:
    """PENDING -> SOAKING: the index stopped being read; start the soak clock.
    Anchors `reclaim_stopped_reading_at` to now (DB clock). No-op returning False
    unless currently PENDING, so a repeat/out-of-order call can't re-stamp the anchor
    and extend the soak. Caller commits."""
    if search_settings.reclaim_status != IndexReclaimStatus.PENDING:
        return False
    search_settings.reclaim_status = IndexReclaimStatus.SOAKING
    search_settings.reclaim_stopped_reading_at = func.now()
    search_settings.reclaim_attempts = 0
    search_settings.reclaim_last_error = None
    return True


def advance_to_deleting__no_commit(search_settings: SearchSettings) -> bool:
    """SOAKING -> DELETING: soak elapsed + new index healthy. No-op returning False
    unless currently SOAKING, so a call can't skip the soak. Caller commits."""
    if search_settings.reclaim_status != IndexReclaimStatus.SOAKING:
        return False
    search_settings.reclaim_status = IndexReclaimStatus.DELETING
    search_settings.reclaim_attempts = 0
    search_settings.reclaim_last_error = None
    return True


def advance_to_reclaimed__no_commit(search_settings: SearchSettings) -> bool:
    """DELETING -> RECLAIMED: the old index's data is gone. Terminal success — the PAST
    row is KEPT as the durable record (we only delete the OpenSearch index, not the row).
    No-op returning False unless currently DELETING. Caller commits."""
    if search_settings.reclaim_status != IndexReclaimStatus.DELETING:
        return False
    search_settings.reclaim_status = IndexReclaimStatus.RECLAIMED
    search_settings.reclaim_attempts = 0
    search_settings.reclaim_last_error = None
    return True


def record_failure__no_commit(
    search_settings: SearchSettings,
    error: str,
    max_attempts: int,
) -> bool:
    """Record a reclaim-step failure. Bumps the attempt counter; parks the row as
    BLOCKED once it reaches `max_attempts`. Returns True if it is now BLOCKED.
    Caller commits."""
    search_settings.reclaim_attempts = (search_settings.reclaim_attempts or 0) + 1
    search_settings.reclaim_last_error = error[:2000]
    if search_settings.reclaim_attempts >= max_attempts:
        search_settings.reclaim_status = IndexReclaimStatus.BLOCKED
        return True
    return False


def find_unreclaimed_past_by_index_name(
    db_session: Session, index_name: str
) -> list[SearchSettings]:
    """PAST rows sharing this physical index_name whose data is not yet reclaimed.
    The name-reuse guard uses this: ALT_INDEX_SUFFIX alternation can make a new FUTURE's
    index_name equal an old PAST's, and reusing it would adopt the old data. Multiple
    generations can share one physical index, so this returns all of them."""
    stmt = select(SearchSettings).where(
        SearchSettings.status == IndexModelStatus.PAST,
        SearchSettings.index_name == index_name,
        SearchSettings.reclaim_status.in_(_INDEX_PRESENT_RECLAIM_STATUSES),
    )
    return list(db_session.scalars(stmt))
