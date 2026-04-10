"""API endpoints for tenant configuration."""

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import DocumentSource
from onyx.db.connector import fetch_connectors
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.proposal_review.api.models import ConfigResponse
from onyx.server.features.proposal_review.api.models import ConfigUpdate
from onyx.server.features.proposal_review.api.models import JiraConnectorInfo
from onyx.server.features.proposal_review.db import config as config_db
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


@router.get("/config")
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


@router.put("/config")
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


@router.get("/jira-connectors")
def list_jira_connectors(
    _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[JiraConnectorInfo]:
    """List all Jira connectors available to this tenant."""
    connectors = fetch_connectors(db_session, sources=[DocumentSource.JIRA])
    results: list[JiraConnectorInfo] = []
    for c in connectors:
        cfg = c.connector_specific_config or {}
        project_key = cfg.get("project_key", "")
        base_url = cfg.get("jira_base_url", "")
        results.append(
            JiraConnectorInfo(
                id=c.id,
                name=c.name,
                project_key=project_key,
                project_url=base_url,
            )
        )
    return results


@router.get("/jira-connectors/{connector_id}/metadata-keys")
def get_connector_metadata_keys(
    connector_id: int,
    _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[str]:
    """Return the distinct doc_metadata keys across all documents for a connector."""
    return config_db.get_connector_metadata_keys(connector_id, db_session)
