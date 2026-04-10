"""DB operations for tenant configuration."""

from datetime import datetime
from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_config(
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewConfig | None:
    """Get the config row for a tenant (there is at most one)."""
    return (
        db_session.query(ProposalReviewConfig)
        .filter(ProposalReviewConfig.tenant_id == tenant_id)
        .one_or_none()
    )


def upsert_config(
    tenant_id: str,
    db_session: Session,
    jira_connector_id: int | None = None,
    jira_project_key: str | None = None,
    field_mapping: dict[str, Any] | None = None,
    jira_writeback: dict[str, Any] | None = None,
) -> ProposalReviewConfig:
    """Create or update the tenant config."""
    config = get_config(tenant_id, db_session)

    if config:
        if jira_connector_id is not None:
            config.jira_connector_id = jira_connector_id
        if jira_project_key is not None:
            config.jira_project_key = jira_project_key
        if field_mapping is not None:
            config.field_mapping = field_mapping
        if jira_writeback is not None:
            config.jira_writeback = jira_writeback
        config.updated_at = datetime.now(timezone.utc)
        db_session.flush()
        logger.info(f"Updated proposal review config for tenant {tenant_id}")
        return config

    config = ProposalReviewConfig(
        tenant_id=tenant_id,
        jira_connector_id=jira_connector_id,
        jira_project_key=jira_project_key,
        field_mapping=field_mapping,
        jira_writeback=jira_writeback,
    )
    db_session.add(config)
    db_session.flush()
    logger.info(f"Created proposal review config for tenant {tenant_id}")
    return config
