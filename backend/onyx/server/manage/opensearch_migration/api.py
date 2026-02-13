from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.opensearch_migration import get_opensearch_migration_state
from onyx.db.opensearch_migration import get_opensearch_retrieval_state
from onyx.db.opensearch_migration import set_enable_opensearch_retrieval_with_commit
from onyx.server.manage.opensearch_migration.models import (
    OpenSearchMigrationStatusResponse,
)
from onyx.server.manage.opensearch_migration.models import (
    OpenSearchRetrievalStatusRequest,
)
from onyx.server.manage.opensearch_migration.models import (
    OpenSearchRetrievalStatusResponse,
)

admin_router = APIRouter(prefix="/admin/opensearch-migration")


@admin_router.get("/status")
def get_opensearch_migration_status(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> OpenSearchMigrationStatusResponse:
    total_chunks_migrated, created_at, migration_completed_at = (
        get_opensearch_migration_state(db_session)
    )
    return OpenSearchMigrationStatusResponse(
        total_chunks_migrated=total_chunks_migrated,
        created_at=created_at,
        migration_completed_at=migration_completed_at,
    )


@admin_router.get("/retrieval")
def get_opensearch_retrieval_status(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> OpenSearchRetrievalStatusResponse:
    enable_opensearch_retrieval = get_opensearch_retrieval_state(db_session)
    return OpenSearchRetrievalStatusResponse(
        enable_opensearch_retrieval=enable_opensearch_retrieval,
    )


@admin_router.put("/retrieval")
def set_opensearch_retrieval_status(
    request: OpenSearchRetrievalStatusRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> OpenSearchRetrievalStatusResponse:
    set_enable_opensearch_retrieval_with_commit(
        db_session, request.enable_opensearch_retrieval
    )
    return OpenSearchRetrievalStatusResponse(
        enable_opensearch_retrieval=request.enable_opensearch_retrieval,
    )
