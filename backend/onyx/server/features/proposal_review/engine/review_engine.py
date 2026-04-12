"""Celery tasks that orchestrate proposal review — parallel rule evaluation."""

from datetime import datetime
from datetime import timezone

from celery import group
from celery import shared_task
from sqlalchemy import update

from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


@shared_task(
    name="run_proposal_review",
    bind=True,
    ignore_result=True,
    soft_time_limit=3600,
    time_limit=3660,
)
def run_proposal_review(_self: object, review_run_id: str, tenant_id: str) -> None:
    """Parent task: orchestrates rule evaluation for a review run.

    1. Set run status=RUNNING
    2. Call get_proposal_context() once
    3. Try to auto-fetch FOA if opportunity_id in metadata and no FOA doc
    4. Get all active rules for the run's ruleset
    5. Set total_rules on the run
    6. Evaluate rules in parallel via Celery group of evaluate_single_rule tasks
    7. After all complete: set status=COMPLETED
    8. On error: set status=FAILED
    """
    # Set tenant context for DB access
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    try:
        from onyx.tracing.framework.create import trace

        with trace(
            "proposal_review",
            metadata={"review_run_id": review_run_id},
        ):
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

    # Step 6: Evaluate rules in parallel via Celery group
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    task_group = group(
        evaluate_single_rule.s(review_run_id, str(rule_info["id"]), tenant_id)
        for rule_info in rule_data
    )
    result = task_group.apply_async(expires=3600)

    # Block until all child tasks finish. We are already inside a Celery task
    # with a 3600s time limit, so blocking is safe. disable_sync_subtasks=False
    # is required because Celery disallows .get() inside tasks by default.
    result.get(disable_sync_subtasks=False, timeout=3500)

    # Step 7: Mark run as completed
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if run:
            run.status = "COMPLETED"
            run.completed_at = datetime.now(timezone.utc)
            db_session.commit()

    logger.info(
        f"Review run {review_run_id} completed: "
        f"{len(rule_data)} rules evaluated in parallel"
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


@shared_task(
    name="evaluate_single_rule", bind=True, soft_time_limit=300, time_limit=330
)
def evaluate_single_rule(
    _self: object, review_run_id: str, rule_id: str, tenant_id: str
) -> None:
    """Child task: evaluates one rule in parallel via Celery group.

    Each child task independently re-assembles proposal context, evaluates
    the rule, saves the finding, and atomically increments completed_rules.
    On evaluation failure, an error finding (NEEDS_REVIEW) is saved so the
    officer sees which rule failed without crashing the group.
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

        try:
            _evaluate_and_save(review_run_id, rule_id, proposal_id, context)
        except Exception as e:
            logger.error(
                f"Rule {rule_id} evaluation failed: {e}",
                exc_info=True,
            )
            # Save an error finding so the officer sees which rule failed
            _save_error_finding(
                review_run_id=review_run_id,
                rule_id=rule_id,
                proposal_id=proposal_id,
                error=str(e),
            )

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


@shared_task(name="run_checklist_import", bind=True, ignore_result=True)
def run_checklist_import(_self: object, import_job_id: str, tenant_id: str) -> None:
    """Background task: decompose a checklist via LLM and save rules."""
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    try:
        from onyx.tracing.framework.create import trace

        with trace(
            "checklist_import",
            metadata={"import_job_id": import_job_id},
        ):
            _execute_checklist_import(import_job_id)
    except Exception as e:
        logger.error(f"Import job {import_job_id} failed: {e}", exc_info=True)
        _mark_import_failed(import_job_id, str(e))
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.set(None)


def _execute_checklist_import(import_job_id: str) -> None:
    """Core import logic, separated for traceability."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import as_completed
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llm
    from onyx.server.features.proposal_review.db import imports as imports_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.engine.checklist_importer import (
        decompose_checklist_item,
        enumerate_checklist_items,
    )

    job_uuid = UUID(import_job_id)
    parallel_workers = int(
        os.environ.get("PROPOSAL_REVIEW_IMPORT_PARALLEL_WORKERS", "4")
    )

    # Step 1: Mark RUNNING and load job data
    with get_session_with_current_tenant() as db_session:
        job = imports_db.get_import_job(job_uuid, db_session)
        if not job:
            raise ValueError(f"Import job {import_job_id} not found")

        job.status = "RUNNING"
        db_session.commit()

        ruleset_id = job.ruleset_id
        extracted_text = job.extracted_text

    llm = get_default_llm(timeout=300)

    # Step 2: Enumerate checklist items
    items = enumerate_checklist_items(extracted_text, llm)

    if not items:
        logger.warning(f"Import {import_job_id}: no checklist items found")
        with get_session_with_current_tenant() as db_session:
            job = imports_db.get_import_job(job_uuid, db_session)
            if job:
                job.status = "COMPLETED"
                job.completed_at = datetime.now(timezone.utc)
                db_session.commit()
        return

    # Split items with too many sub-checks into smaller pieces so each
    # LLM call produces bounded output.  The threshold is conservative —
    # 5 sub-checks ≈ 2-4K output tokens, safe for any model.
    max_sub_checks = int(
        os.environ.get("PROPOSAL_REVIEW_IMPORT_MAX_SUB_CHECKS_PER_CALL", "5")
    )
    work_items = _split_large_items(items, max_sub_checks)

    logger.info(
        f"Import {import_job_id}: enumerated {len(items)} items "
        f"({len(work_items)} work units after splitting), "
        f"decomposing with {parallel_workers} workers"
    )

    # Step 3: Decompose each work item in parallel, persist as each completes
    rules_created = 0
    failed_items: list[str] = []
    workers = min(parallel_workers, len(work_items))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_item = {
            executor.submit(decompose_checklist_item, item, extracted_text, llm): item
            for item in work_items
        }

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                rule_dicts = future.result()
            except Exception as e:
                logger.error(
                    f"  [{item.id}] '{item.name}' failed: {e}",
                    exc_info=True,
                )
                failed_items.append(item.name)
                continue

            if not rule_dicts:
                continue

            # Persist this item's rules in their own transaction
            with get_session_with_current_tenant() as db_session:
                for rd in rule_dicts:
                    rule = rulesets_db.create_rule(
                        ruleset_id=ruleset_id,
                        name=rd["name"],
                        description=rd.get("description"),
                        category=rd.get("category"),
                        rule_type=rd.get("rule_type", "CUSTOM_NL"),
                        rule_intent=rd.get("rule_intent", "CHECK"),
                        prompt_template=rd["prompt_template"],
                        source="IMPORTED",
                        is_hard_stop=False,
                        priority=0,
                        db_session=db_session,
                    )
                    rule.is_active = False
                    db_session.flush()

                rules_created += len(rule_dicts)

                # Update progress so the frontend can poll it
                job = imports_db.get_import_job(job_uuid, db_session)
                if job:
                    job.rules_created = rules_created

                db_session.commit()

            logger.info(
                f"  [{item.id}] '{item.name}': "
                f"{len(rule_dicts)} rules persisted "
                f"({rules_created} total)"
            )

    # Step 4: Mark completed
    with get_session_with_current_tenant() as db_session:
        job = imports_db.get_import_job(job_uuid, db_session)
        if job:
            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc)
            db_session.commit()

    status = f"{rules_created} rules created"
    if failed_items:
        status += f", {len(failed_items)} items failed: {failed_items}"
    logger.info(f"Import job {import_job_id} completed: {status}")


def _mark_import_failed(import_job_id: str, error: str) -> None:
    """Mark an import job as FAILED."""
    from uuid import UUID

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import imports as imports_db

    try:
        with get_session_with_current_tenant() as db_session:
            job = imports_db.get_import_job(UUID(import_job_id), db_session)
            if job:
                job.status = "FAILED"
                job.error_message = error
                job.completed_at = datetime.now(timezone.utc)
                db_session.commit()
    except Exception as e:
        logger.error(f"Failed to mark import job {import_job_id} as FAILED: {e}")


def _split_large_items(
    items: list,  # list[ChecklistItem] — untyped to avoid top-level import
    max_sub_checks: int,
) -> list:
    """Split checklist items with many sub-checks into smaller work units.

    Each returned item has at most *max_sub_checks* sub-checks, keeping the
    LLM output bounded regardless of how large the original item was.  Items
    that are already within the limit pass through unchanged.
    """
    from onyx.server.features.proposal_review.engine.checklist_importer import (
        ChecklistItem,
    )

    work_items: list[ChecklistItem] = []
    for item in items:
        if len(item.sub_checks) <= max_sub_checks:
            work_items.append(item)
            continue

        # Split into batches, each becoming its own work unit
        for batch_idx in range(0, len(item.sub_checks), max_sub_checks):
            batch = item.sub_checks[batch_idx : batch_idx + max_sub_checks]
            part_num = (batch_idx // max_sub_checks) + 1
            work_items.append(
                ChecklistItem(
                    id=f"{item.id}-p{part_num}",
                    name=item.name,
                    category=item.category,
                    description=item.description,
                    sub_checks=batch,
                )
            )

    return work_items


@shared_task(
    name="sync_decision_to_jira",
    bind=True,
    ignore_result=True,
    soft_time_limit=60,
    time_limit=90,
)
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
