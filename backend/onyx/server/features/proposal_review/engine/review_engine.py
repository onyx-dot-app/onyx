"""Celery tasks that orchestrate proposal review — parallel rule evaluation."""

from datetime import datetime
from datetime import timezone

from celery import shared_task
from sqlalchemy import update

from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


@shared_task(bind=True, ignore_result=True, soft_time_limit=3600, time_limit=3660)
def run_proposal_review(_self: object, review_run_id: str, tenant_id: str) -> None:
    """Parent task: orchestrates rule evaluation for a review run.

    1. Set run status=RUNNING
    2. Call get_proposal_context() once
    3. Try to auto-fetch FOA if opportunity_id in metadata and no FOA doc
    4. Get all active rules for the run's ruleset
    5. Set total_rules on the run
    6. Evaluate each rule sequentially (V1 — no Celery subtasks)
    7. After all complete: set status=COMPLETED
    8. On error: set status=FAILED
    """
    # Set tenant context for DB access
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    try:
        _execute_review(review_run_id)
    except Exception as e:
        logger.error(f"Review run {review_run_id} failed: {e}", exc_info=True)
        _mark_run_failed(review_run_id)
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


def _execute_review(review_run_id: str) -> None:
    """Core review logic, separated for testability."""
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.engine.context_assembler import (
        get_proposal_context,
    )
    from onyx.server.features.proposal_review.engine.foa_fetcher import fetch_foa

    run_uuid = UUID(review_run_id)

    # Step 1: Set run status to RUNNING
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if not run:
            raise ValueError(f"Review run {review_run_id} not found")

        run.status = "RUNNING"
        run.started_at = datetime.now(timezone.utc)
        db_session.commit()

        proposal_id = run.proposal_id
        ruleset_id = run.ruleset_id

    # Step 2: Assemble proposal context
    with get_session_with_current_tenant() as db_session:
        context = get_proposal_context(proposal_id, db_session)

    # Step 3: Try to auto-fetch FOA if opportunity_id is in metadata
    opportunity_id = context.metadata.get("opportunity_id") or context.metadata.get(
        "funding_opportunity_number"
    )
    if opportunity_id and not context.foa_text:
        logger.info(f"Attempting to auto-fetch FOA for opportunity_id={opportunity_id}")
        try:
            with get_session_with_current_tenant() as db_session:
                foa_text = fetch_foa(opportunity_id, proposal_id, db_session)
                db_session.commit()
                if foa_text:
                    context.foa_text = foa_text
                    logger.info(f"Auto-fetched FOA: {len(foa_text)} chars")
        except Exception as e:
            logger.warning(f"FOA auto-fetch failed (non-fatal): {e}")

    # Step 4: Get all active rules for the ruleset
    with get_session_with_current_tenant() as db_session:
        rules = rulesets_db.list_rules_by_ruleset(
            ruleset_id, db_session, active_only=True
        )
        # Detach rules from the session so we can use them outside
        rule_data = [
            {
                "id": rule.id,
                "name": rule.name,
                "prompt_template": rule.prompt_template,
                "rule_type": rule.rule_type,
                "rule_intent": rule.rule_intent,
                "is_hard_stop": rule.is_hard_stop,
                "category": rule.category,
            }
            for rule in rules
        ]

    if not rule_data:
        logger.warning(f"No active rules found for ruleset {ruleset_id}")
        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(run_uuid, db_session)
            if run:
                run.status = "COMPLETED"
                run.completed_at = datetime.now(timezone.utc)
                db_session.commit()
        return

    # Step 5: Update total_rules on the run
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if run:
            run.total_rules = len(rule_data)
            db_session.commit()

    # Step 6: Evaluate each rule sequentially
    completed = 0
    for rule_info in rule_data:
        try:
            _evaluate_and_save(
                review_run_id=review_run_id,
                rule_id=str(rule_info["id"]),
                proposal_id=proposal_id,
                context=context,
            )
            completed += 1
        except Exception as e:
            logger.error(
                f"Rule '{rule_info['name']}' (id={rule_info['id']}) failed: {e}",
                exc_info=True,
            )
            # Save an error finding so the officer sees which rule failed
            _save_error_finding(
                review_run_id=review_run_id,
                rule_id=str(rule_info["id"]),
                proposal_id=proposal_id,
                error=str(e),
            )
            completed += 1

        # Increment completed_rules counter
        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(run_uuid, db_session)
            if run:
                run.completed_rules = completed
                db_session.commit()

    # Step 7: Mark run as completed
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if run:
            run.status = "COMPLETED"
            run.completed_at = datetime.now(timezone.utc)
            run.completed_rules = completed
            db_session.commit()

    logger.info(
        f"Review run {review_run_id} completed: {completed}/{len(rule_data)} rules evaluated"
    )


def _evaluate_and_save(
    review_run_id: str,
    rule_id: str,
    proposal_id: str,
    context: object,  # ProposalContext — typed as object to avoid circular import at module level
) -> None:
    """Evaluate a single rule and save the finding to DB."""
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.engine.rule_evaluator import (
        evaluate_rule,
    )

    rule_uuid = UUID(rule_id)
    run_uuid = UUID(review_run_id)

    # Load the rule from DB
    with get_session_with_current_tenant() as db_session:
        rule = rulesets_db.get_rule(rule_uuid, db_session)
        if not rule:
            raise ValueError(f"Rule {rule_id} not found")

        # Evaluate the rule
        result = evaluate_rule(rule, context, db_session)

        # Save finding
        findings_db.create_finding(
            proposal_id=proposal_id,
            rule_id=rule_uuid,
            review_run_id=run_uuid,
            verdict=result["verdict"],
            confidence=result.get("confidence"),
            evidence=result.get("evidence"),
            explanation=result.get("explanation"),
            suggested_action=result.get("suggested_action"),
            llm_model=result.get("llm_model"),
            llm_tokens_used=result.get("llm_tokens_used"),
            db_session=db_session,
        )
        db_session.commit()

    logger.debug(f"Rule {rule_id} evaluated: verdict={result['verdict']}")


def _save_error_finding(
    review_run_id: str,
    rule_id: str,
    proposal_id: str,
    error: str,
) -> None:
    """Save an error finding when a rule evaluation fails."""
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db

    try:
        with get_session_with_current_tenant() as db_session:
            findings_db.create_finding(
                proposal_id=proposal_id,
                rule_id=UUID(rule_id),
                review_run_id=UUID(review_run_id),
                verdict="NEEDS_REVIEW",
                confidence="LOW",
                evidence=None,
                explanation=f"Rule evaluation failed with error: {error}",
                suggested_action="Manual review required due to system error.",
                db_session=db_session,
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Failed to save error finding for rule {rule_id}: {e}")


def _mark_run_failed(review_run_id: str) -> None:
    """Mark a review run as FAILED."""
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db

    try:
        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(UUID(review_run_id), db_session)
            if run:
                run.status = "FAILED"
                run.completed_at = datetime.now(timezone.utc)
                db_session.commit()
    except Exception as e:
        logger.error(f"Failed to mark run {review_run_id} as FAILED: {e}")


@shared_task(bind=True, ignore_result=True, soft_time_limit=300, time_limit=330)
def evaluate_single_rule(
    _self: object, review_run_id: str, rule_id: str, tenant_id: str
) -> None:
    """Child task: evaluates one rule (for future parallel execution).

    Currently not used in V1 — rules are evaluated sequentially in
    run_proposal_review. This task exists for future migration to
    parallel execution via Celery groups.
    """
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        from uuid import UUID

        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.server.features.proposal_review.db import findings as findings_db
        from onyx.server.features.proposal_review.engine.context_assembler import (
            get_proposal_context,
        )

        run_uuid = UUID(review_run_id)

        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(run_uuid, db_session)
            if not run:
                raise ValueError(f"Review run {review_run_id} not found")
            proposal_id = run.proposal_id

        # Re-assemble context (each subtask is independent)
        with get_session_with_current_tenant() as db_session:
            context = get_proposal_context(proposal_id, db_session)

        _evaluate_and_save(review_run_id, rule_id, proposal_id, context)

        # Increment completed_rules atomically to avoid race conditions
        with get_session_with_current_tenant() as db_session:
            from onyx.server.features.proposal_review.db.models import (
                ProposalReviewRun,
            )

            db_session.execute(
                update(ProposalReviewRun)
                .where(ProposalReviewRun.id == run_uuid)
                .values(completed_rules=ProposalReviewRun.completed_rules + 1)
            )
            db_session.commit()

    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


@shared_task(bind=True, ignore_result=True, soft_time_limit=60, time_limit=90)
def sync_decision_to_jira(_self: object, proposal_id: str, tenant_id: str) -> None:
    """Writes officer decision back to Jira.

    Dispatched from the sync-jira API endpoint.
    """
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        from uuid import UUID

        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.server.features.proposal_review.engine.jira_sync import sync_to_jira

        with get_session_with_current_tenant() as db_session:
            sync_to_jira(UUID(proposal_id), db_session)
            db_session.commit()

        logger.info(f"Jira sync completed for proposal {proposal_id}")

    except Exception as e:
        logger.error(f"Jira sync failed for proposal {proposal_id}: {e}", exc_info=True)
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)
