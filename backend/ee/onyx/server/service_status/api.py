from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import SearchSettings, User
from onyx.db.search_settings import (
    get_current_search_settings,
    get_secondary_search_settings,
)
from onyx.document_index.opensearch.cluster_status import (
    OnyxIndexRef,
    collect_cluster_status,
)
from onyx.document_index.opensearch.models import ClusterStatus
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

router = APIRouter(prefix="/admin/service-status")

CLUSTER_STATUS_KEY = "opensearch_cluster_status"
# Each read costs several cluster API calls, so page loads share one result.
CLUSTER_STATUS_TTL_SECONDS = 60
# A refresh skips the shared result only when it is at least this old.
CLUSTER_STATUS_MIN_REFRESH_SECONDS = 10


def _index_ref(search_settings: SearchSettings, is_current: bool) -> OnyxIndexRef:
    return OnyxIndexRef(
        index_name=search_settings.index_name,
        is_current=is_current,
        model_name=search_settings.model_name,
        model_dim=search_settings.final_embedding_dim,
        vector_quantization=search_settings.vector_quantization,
    )


@router.get("/opensearch")
def read_opensearch_status(
    refresh: bool = False,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ClusterStatus:
    # Cloud shares the cluster across tenants, so its numbers are not a tenant's.
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Service status is only available on self-hosted deployments.",
        )
    if DISABLE_VECTOR_DB:
        raise OnyxError(
            OnyxErrorCode.FEATURE_DISABLED,
            "This deployment runs without a document index.",
        )

    cache: CacheBackend = get_shared_cache_backend()
    raw: bytes | None = cache.get(CLUSTER_STATUS_KEY)
    if raw is not None:
        cached: ClusterStatus = ClusterStatus.model_validate_json(raw)
        age: float = (datetime.now(timezone.utc) - cached.checked_at).total_seconds()
        if not refresh or age < CLUSTER_STATUS_MIN_REFRESH_SECONDS:
            return cached

    indexes: list[OnyxIndexRef] = [
        _index_ref(get_current_search_settings(db_session), is_current=True)
    ]
    secondary: SearchSettings | None = get_secondary_search_settings(db_session)
    if secondary is not None:
        indexes.append(_index_ref(secondary, is_current=False))
    try:
        status: ClusterStatus = collect_cluster_status(indexes)
    except Exception as e:
        logger.exception("Unable to read the OpenSearch cluster status")
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "OpenSearch did not return its status. Check that the cluster is reachable.",
        ) from e
    cache.set(
        CLUSTER_STATUS_KEY, status.model_dump_json(), ex=CLUSTER_STATUS_TTL_SECONDS
    )
    return status
