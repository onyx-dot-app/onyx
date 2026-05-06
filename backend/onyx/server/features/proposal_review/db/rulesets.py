"""DB operations for rulesets and rules."""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.proposal_review.db.models import ProposalReviewRule
from onyx.server.features.proposal_review.db.models import ProposalReviewRuleset
from onyx.utils.logger import setup_logger

logger = setup_logger()

_RULESET_UPDATABLE_FIELDS = frozenset(
    {"name", "description", "is_default", "is_active"}
)
_RULE_UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "category",
        "rule_type",
        "rule_intent",
        "prompt_template",
        "authority",
        "is_hard_stop",
        "priority",
        "is_active",
        "refinement_needed",
        "refinement_question",
    }
)


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
    logger.info("Created ruleset %s '%s' for tenant %s", ruleset.id, name, tenant_id)
    return ruleset


def update_ruleset(
    ruleset_id: UUID,
    tenant_id: str,
    db_session: Session,
    updates: dict[str, Any],
) -> ProposalReviewRuleset | None:
    """Update a ruleset. Returns None if not found."""
    ruleset = get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        return None

    for field, value in updates.items():
        if field not in _RULESET_UPDATABLE_FIELDS:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, f"Cannot update field: {field}"
            )
        if field == "is_default" and value:
            _clear_default_ruleset(tenant_id, db_session)
        setattr(ruleset, field, value)

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
    logger.info("Deleted ruleset %s", ruleset_id)
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


def get_rule_with_tenant_check(
    rule_id: UUID,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewRule | None:
    """Get a single rule by ID, validating it belongs to the given tenant.

    Joins with the ruleset table so the tenant check happens in one query,
    eliminating the race between separate get_rule + get_ruleset calls.
    """
    return (
        db_session.query(ProposalReviewRule)
        .join(
            ProposalReviewRuleset,
            ProposalReviewRule.ruleset_id == ProposalReviewRuleset.id,
        )
        .filter(
            ProposalReviewRule.id == rule_id,
            ProposalReviewRuleset.tenant_id == tenant_id,
        )
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
    refinement_needed: bool = False,
    refinement_question: str | None = None,
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
        refinement_needed=refinement_needed,
        refinement_question=refinement_question,
    )
    db_session.add(rule)
    db_session.flush()
    logger.info("Created rule %s '%s' in ruleset %s", rule.id, name, ruleset_id)
    return rule


def update_rule(
    rule_id: UUID,
    db_session: Session,
    updates: dict[str, Any],
) -> ProposalReviewRule | None:
    """Update a rule. Returns None if not found."""
    rule = get_rule(rule_id, db_session)
    if not rule:
        return None

    for field, value in updates.items():
        if field not in _RULE_UPDATABLE_FIELDS:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, f"Cannot update field: {field}"
            )
        setattr(rule, field, value)

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
    logger.info("Deleted rule %s", rule_id)
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
    base_query = db_session.query(ProposalReviewRule).filter(
        ProposalReviewRule.id.in_(rule_ids),
        ProposalReviewRule.ruleset_id == ruleset_id,
    )

    if action == "delete":
        count = base_query.delete(synchronize_session="fetch")
    elif action in ("activate", "deactivate"):
        count = base_query.update(
            {
                ProposalReviewRule.is_active: action == "activate",
                ProposalReviewRule.updated_at: datetime.now(timezone.utc),
            },
            synchronize_session="fetch",
        )
    else:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"Unknown bulk action: {action}")

    db_session.flush()
    logger.info("Bulk %s on %s rules", action, count)
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
