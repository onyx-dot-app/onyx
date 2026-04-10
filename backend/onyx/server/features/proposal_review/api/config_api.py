"""API endpoints for tenant configuration."""

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.proposal_review.api.models import ConfigResponse
from onyx.server.features.proposal_review.api.models import ConfigUpdate
from onyx.server.features.proposal_review.db import config as config_db
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


@router.get("/config", response_model=ConfigResponse)
def get_config(
    _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ConfigResponse:
    """Get the tenant's proposal review configuration."""
    tenant_id = get_current_tenant_id()
    config = config_db.get_config(tenant_id, db_session)
    if not config:
        # Return a default empty config rather than 404
        config = config_db.upsert_config(tenant_id, db_session)
        db_session.commit()
    return ConfigResponse.from_model(config)


@router.put("/config", response_model=ConfigResponse)
def update_config(
    request: ConfigUpdate,
    _user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> ConfigResponse:
    """Update the tenant's proposal review configuration."""
    tenant_id = get_current_tenant_id()
    config = config_db.upsert_config(
        tenant_id=tenant_id,
        jira_connector_id=request.jira_connector_id,
        jira_project_key=request.jira_project_key,
        field_mapping=request.field_mapping,
        jira_writeback=request.jira_writeback,
        db_session=db_session,
    )
    db_session.commit()
    return ConfigResponse.from_model(config)
