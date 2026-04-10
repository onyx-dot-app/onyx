"""DB operations for rulesets and rules."""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewRule
from onyx.server.features.proposal_review.db.models import ProposalReviewRuleset
from onyx.utils.logger import setup_logger

logger = setup_logger()


# =============================================================================
# Ruleset CRUD
# =============================================================================


def list_rulesets(
    tenant_id: str,
    db_session: Session,
    active_only: bool = False,
) -> list[ProposalReviewRuleset]:
    """List all rulesets for a tenant."""
    query = (
        db_session.query(ProposalReviewRuleset)
        .filter(ProposalReviewRuleset.tenant_id == tenant_id)
        .options(selectinload(ProposalReviewRuleset.rules))
        .order_by(desc(ProposalReviewRuleset.created_at))
    )
    if active_only:
        query = query.filter(ProposalReviewRuleset.is_active.is_(True))
    return query.all()


def get_ruleset(
    ruleset_id: UUID,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewRuleset | None:
    """Get a single ruleset by ID with all its rules."""
    return (
        db_session.query(ProposalReviewRuleset)
        .filter(
            ProposalReviewRuleset.id == ruleset_id,
            ProposalReviewRuleset.tenant_id == tenant_id,
        )
        .options(selectinload(ProposalReviewRuleset.rules))
        .one_or_none()
    )


def create_ruleset(
    tenant_id: str,
    name: str,
    db_session: Session,
    description: str | None = None,
    is_default: bool = False,
    created_by: UUID | None = None,
) -> ProposalReviewRuleset:
    """Create a new ruleset."""
    # If this ruleset is default, un-default any existing default
    if is_default:
        _clear_default_ruleset(tenant_id, db_session)

    ruleset = ProposalReviewRuleset(
        tenant_id=tenant_id,
        name=name,
        description=description,
        is_default=is_default,
        created_by=created_by,
    )
    db_session.add(ruleset)
    db_session.flush()
    logger.info(f"Created ruleset {ruleset.id} '{name}' for tenant {tenant_id}")
    return ruleset


def update_ruleset(
    ruleset_id: UUID,
    tenant_id: str,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    is_default: bool | None = None,
    is_active: bool | None = None,
) -> ProposalReviewRuleset | None:
    """Update a ruleset. Returns None if not found."""
    ruleset = get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        return None

    if name is not None:
        ruleset.name = name
    if description is not None:
        ruleset.description = description
    if is_default is not None:
        if is_default:
            _clear_default_ruleset(tenant_id, db_session)
        ruleset.is_default = is_default
    if is_active is not None:
        ruleset.is_active = is_active

    ruleset.updated_at = datetime.now(timezone.utc)
    db_session.flush()
    return ruleset


def delete_ruleset(
    ruleset_id: UUID,
    tenant_id: str,
    db_session: Session,
) -> bool:
    """Delete a ruleset. Returns False if not found."""
    ruleset = get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        return False
    db_session.delete(ruleset)
    db_session.flush()
    logger.info(f"Deleted ruleset {ruleset_id}")
    return True


def _clear_default_ruleset(tenant_id: str, db_session: Session) -> None:
    """Un-default any existing default ruleset for a tenant."""
    db_session.query(ProposalReviewRuleset).filter(
        ProposalReviewRuleset.tenant_id == tenant_id,
        ProposalReviewRuleset.is_default.is_(True),
    ).update({ProposalReviewRuleset.is_default: False})
    db_session.flush()


# =============================================================================
# Rule CRUD
# =============================================================================


def list_rules_by_ruleset(
    ruleset_id: UUID,
    db_session: Session,
    active_only: bool = False,
) -> list[ProposalReviewRule]:
    """List all rules in a ruleset."""
    query = (
        db_session.query(ProposalReviewRule)
        .filter(ProposalReviewRule.ruleset_id == ruleset_id)
        .order_by(ProposalReviewRule.priority)
    )
    if active_only:
        query = query.filter(ProposalReviewRule.is_active.is_(True))
    return query.all()


def get_rule(
    rule_id: UUID,
    db_session: Session,
) -> ProposalReviewRule | None:
    """Get a single rule by ID."""
    return (
        db_session.query(ProposalReviewRule)
        .filter(ProposalReviewRule.id == rule_id)
        .one_or_none()
    )


def create_rule(
    ruleset_id: UUID,
    name: str,
    rule_type: str,
    prompt_template: str,
    db_session: Session,
    description: str | None = None,
    category: str | None = None,
    rule_intent: str = "CHECK",
    source: str = "MANUAL",
    authority: str | None = None,
    is_hard_stop: bool = False,
    priority: int = 0,
) -> ProposalReviewRule:
    """Create a new rule within a ruleset."""
    rule = ProposalReviewRule(
        ruleset_id=ruleset_id,
        name=name,
        description=description,
        category=category,
        rule_type=rule_type,
        rule_intent=rule_intent,
        prompt_template=prompt_template,
        source=source,
        authority=authority,
        is_hard_stop=is_hard_stop,
        priority=priority,
    )
    db_session.add(rule)
    db_session.flush()
    logger.info(f"Created rule {rule.id} '{name}' in ruleset {ruleset_id}")
    return rule


def update_rule(
    rule_id: UUID,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    rule_type: str | None = None,
    rule_intent: str | None = None,
    prompt_template: str | None = None,
    authority: str | None = None,
    is_hard_stop: bool | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
) -> ProposalReviewRule | None:
    """Update a rule. Returns None if not found."""
    rule = get_rule(rule_id, db_session)
    if not rule:
        return None

    if name is not None:
        rule.name = name
    if description is not None:
        rule.description = description
    if category is not None:
        rule.category = category
    if rule_type is not None:
        rule.rule_type = rule_type
    if rule_intent is not None:
        rule.rule_intent = rule_intent
    if prompt_template is not None:
        rule.prompt_template = prompt_template
    if authority is not None:
        rule.authority = authority
    if is_hard_stop is not None:
        rule.is_hard_stop = is_hard_stop
    if priority is not None:
        rule.priority = priority
    if is_active is not None:
        rule.is_active = is_active

    rule.updated_at = datetime.now(timezone.utc)
    db_session.flush()
    return rule


def delete_rule(
    rule_id: UUID,
    db_session: Session,
) -> bool:
    """Delete a rule. Returns False if not found."""
    rule = get_rule(rule_id, db_session)
    if not rule:
        return False
    db_session.delete(rule)
    db_session.flush()
    logger.info(f"Deleted rule {rule_id}")
    return True


def bulk_update_rules(
    rule_ids: list[UUID],
    action: str,
    ruleset_id: UUID,
    db_session: Session,
) -> int:
    """Batch activate/deactivate/delete rules.

    Args:
        rule_ids: list of rule IDs
        action: "activate" | "deactivate" | "delete"
        ruleset_id: scope operations to rules within this ruleset

    Returns:
        number of rules affected
    """
    if action == "delete":
        count = (
            db_session.query(ProposalReviewRule)
            .filter(
                ProposalReviewRule.id.in_(rule_ids),
                ProposalReviewRule.ruleset_id == ruleset_id,
            )
            .delete(synchronize_session="fetch")
        )
    elif action == "activate":
        count = (
            db_session.query(ProposalReviewRule)
            .filter(
                ProposalReviewRule.id.in_(rule_ids),
                ProposalReviewRule.ruleset_id == ruleset_id,
            )
            .update(
                {
                    ProposalReviewRule.is_active: True,
                    ProposalReviewRule.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session="fetch",
            )
        )
    elif action == "deactivate":
        count = (
            db_session.query(ProposalReviewRule)
            .filter(
                ProposalReviewRule.id.in_(rule_ids),
                ProposalReviewRule.ruleset_id == ruleset_id,
            )
            .update(
                {
                    ProposalReviewRule.is_active: False,
                    ProposalReviewRule.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session="fetch",
            )
        )
    else:
        raise ValueError(f"Unknown bulk action: {action}")

    db_session.flush()
    logger.info(f"Bulk {action} on {count} rules")
    return count


def count_active_rules(
    ruleset_id: UUID,
    db_session: Session,
) -> int:
    """Count active rules in a ruleset."""
    return (
        db_session.query(ProposalReviewRule)
        .filter(
            ProposalReviewRule.ruleset_id == ruleset_id,
            ProposalReviewRule.is_active.is_(True),
        )
        .count()
    )
