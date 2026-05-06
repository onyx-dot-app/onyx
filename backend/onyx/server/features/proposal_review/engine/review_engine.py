"""Proposal review engine — private helpers for task implementations.

The actual Celery @shared_task definitions live in tasks.py (for autodiscovery).
This module contains the orchestration and evaluation logic they delegate to.
"""

from __future__ import annotations

import contextvars
import os
import time
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timezone
from typing import cast
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import update

from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.server.features.proposal_review.engine.context_assembler import (
        ProposalContext,
    )

logger = setup_logger()


def _execute_review(
    review_run_id: str,
    rule_ids: list[str] | None = None,
) -> None:
    """Core review logic, separated for testability.

    When rule_ids is None, evaluates all active rules in the run's ruleset
    (full run). When rule_ids is provided, deletes the old error findings
    for those rules and re-evaluates only them (retry flow).
    """
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.db.models import ProposalReviewRun
    from onyx.server.features.proposal_review.engine.context_assembler import (
        get_proposal_context,
    )
    from onyx.server.features.proposal_review.engine.foa_fetcher import fetch_foa

    run_uuid = UUID(review_run_id)
    is_retry = rule_ids is not None

    if is_retry and not rule_ids:
        logger.warning("Retry called with empty rule_ids for run %s", review_run_id)
        # Reset status since the API already set it to RUNNING
        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(run_uuid, db_session)
            if run and run.status == "RUNNING":
                run.status = "COMPLETED"
                db_session.commit()
        return

    # Step 1: Set run status to RUNNING; for retries, clean up old findings
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if not run:
            raise ValueError(f"Review run {review_run_id} not found")

        proposal_id = run.proposal_id
        ruleset_id = run.ruleset_id

        if is_retry:
            assert rule_ids is not None  # guaranteed by early return above
            rule_id_set = set(rule_ids)
            # Delete old error findings for the rules being retried
            failed = findings_db.get_failed_findings_for_run(run_uuid, db_session)
            failed_for_rules = [f for f in failed if str(f.rule_id) in rule_id_set]
            if failed_for_rules:
                findings_db.delete_findings(
                    [f.id for f in failed_for_rules], db_session
                )
            # Roll back counters so re-evaluated rules are tracked correctly.
            # completed_rules is rolled back by the number of rules being
            # re-evaluated (not findings — a rule may lack a finding if
            # _save_error_finding itself failed). failed_rules is rolled back
            # by the number of error findings actually deleted.
            run.completed_rules = max(0, run.completed_rules - len(rule_ids))
            run.failed_rules = max(0, run.failed_rules - len(failed_for_rules))
            run.completed_at = None

        run.status = "RUNNING"
        if not is_retry:
            run.started_at = datetime.now(timezone.utc)
        db_session.commit()

    # Step 2: Load review_model from config; assemble proposal context
    review_model: str | None = None
    with get_session_with_current_tenant() as db_session:
        from onyx.server.features.proposal_review.db import config as config_db
        from shared_configs.contextvars import get_current_tenant_id

        config = config_db.get_config(get_current_tenant_id(), db_session)
        if config:
            review_model = config.review_model

    with get_session_with_current_tenant() as db_session:
        context = get_proposal_context(proposal_id, db_session)

    # Step 3: Try to auto-fetch FOA if opportunity_id is in metadata
    opportunity_id = (
        context.metadata.get("opportunity_id")
        or context.metadata.get("funding_opportunity_number")
        or context.metadata.get("Funding Opportunity Number")
    )
    if opportunity_id and not context.foa_text:
        logger.info(
            "Attempting to auto-fetch FOA for opportunity_id=%s", opportunity_id
        )
        try:
            with get_session_with_current_tenant() as db_session:
                foa_text = fetch_foa(opportunity_id, proposal_id, db_session)
                db_session.commit()
                if foa_text:
                    context.foa_text = foa_text
                    logger.info("Auto-fetched FOA: %s chars", len(foa_text))
        except Exception as e:
            logger.warning("FOA auto-fetch failed (non-fatal): %s", e)

    # Step 4: Determine which rules to evaluate
    if is_retry:
        # Retry: use the specific rule IDs passed in
        rules_to_eval = rule_ids
        assert rules_to_eval is not None  # guaranteed by early return above
    else:
        # Full run: get all active rules for the ruleset
        with get_session_with_current_tenant() as db_session:
            rules = rulesets_db.list_rules_by_ruleset(
                ruleset_id, db_session, active_only=True
            )
            rules_to_eval = [str(rule.id) for rule in rules]

        if not rules_to_eval:
            logger.warning("No active rules found for ruleset %s", ruleset_id)
            with get_session_with_current_tenant() as db_session:
                run = findings_db.get_review_run(run_uuid, db_session)
                if run:
                    run.status = "COMPLETED"
                    run.completed_at = datetime.now(timezone.utc)
                    db_session.commit()
            return

        # Step 5: Update total_rules on the run (full run only)
        with get_session_with_current_tenant() as db_session:
            run = findings_db.get_review_run(run_uuid, db_session)
            if run:
                run.total_rules = len(rules_to_eval)
                db_session.commit()

    # Step 6: Evaluate rules in parallel via ThreadPoolExecutor
    parallel_workers = int(os.environ.get("PROPOSAL_REVIEW_PARALLEL_WORKERS", "4"))
    workers = min(parallel_workers, len(rules_to_eval))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_rule_id = {
            executor.submit(
                contextvars.copy_context().run,
                _evaluate_single_rule,
                review_run_id,
                rid,
                proposal_id,
                context,
                review_model,
            ): rid
            for rid in rules_to_eval
        }

        for future in as_completed(future_to_rule_id):
            rid = future_to_rule_id[future]
            succeeded = True
            try:
                succeeded = future.result()
            except Exception as e:
                succeeded = False
                logger.error(
                    "Rule %s failed: %s",
                    rid,
                    e,
                    exc_info=True,
                )

            # Increment completed_rules (and failed_rules on error) atomically
            # so the frontend progress bar always reaches 100%.
            updates: dict = {
                "completed_rules": ProposalReviewRun.completed_rules + 1,
            }
            if not succeeded:
                updates["failed_rules"] = ProposalReviewRun.failed_rules + 1

            with get_session_with_current_tenant() as db_session:
                db_session.execute(
                    update(ProposalReviewRun)
                    .where(ProposalReviewRun.id == run_uuid)
                    .values(**updates)
                )
                db_session.commit()

    # Step 7: Mark run as completed
    with get_session_with_current_tenant() as db_session:
        run = findings_db.get_review_run(run_uuid, db_session)
        if run:
            run.status = "COMPLETED"
            run.completed_at = datetime.now(timezone.utc)
            db_session.commit()

    logger.info(
        "Review run %s completed: %s rules evaluated%s",
        review_run_id,
        len(rules_to_eval),
        " (retry)" if is_retry else "",
    )


def _evaluate_and_save(
    review_run_id: str,
    rule_id: str,
    proposal_id: "UUID",
    context: "ProposalContext",
    review_model: str | None = None,
) -> None:
    """Evaluate a single rule and save the finding to DB."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.server.features.proposal_review.db import findings as findings_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.engine.rule_evaluator import evaluate_rule

    rule_uuid = UUID(rule_id)
    run_uuid = UUID(review_run_id)

    # Load the rule from DB
    with get_session_with_current_tenant() as db_session:
        rule = rulesets_db.get_rule(rule_uuid, db_session)
        if not rule:
            raise ValueError(f"Rule {rule_id} not found")

        # Evaluate the rule
        result = evaluate_rule(rule, context, db_session, review_model=review_model)

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

    logger.debug("Rule %s evaluated: verdict=%s", rule_id, result["verdict"])


def _save_error_finding(
    review_run_id: str,
    rule_id: str,
    proposal_id: "UUID",
    error: str,
) -> None:
    """Save an error finding when a rule evaluation fails."""
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
        logger.error("Failed to save error finding for rule %s: %s", rule_id, e)


def _mark_run_failed(review_run_id: str) -> None:
    """Mark a review run as FAILED."""
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
        logger.error("Failed to mark run %s as FAILED: %s", review_run_id, e)


_MAX_RULE_RETRIES = int(os.environ.get("PROPOSAL_REVIEW_RULE_MAX_RETRIES", "5"))
_RETRY_BACKOFF_BASE = 2  # seconds — retry waits 2s, 4s, 8s, ...
_RATE_LIMIT_BACKOFF = 30  # seconds — longer wait for rate limit errors


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if an exception is a rate limit error."""
    error_str = str(e).lower()
    return "rate_limit" in error_str or "rate limit" in error_str or "429" in error_str


def _evaluate_single_rule(
    review_run_id: str,
    rule_id: str,
    proposal_id: "UUID",
    context: "ProposalContext",
    review_model: str | None = None,
) -> bool:
    """Evaluate one rule, save the finding. Called from ThreadPoolExecutor.

    Context is shared in-memory from the parent — no DB re-fetch needed.
    Retries up to _MAX_RULE_RETRIES times with exponential backoff on failure
    (e.g. LLM timeout). Rate limit errors get longer backoff. On final
    failure, an error finding (NEEDS_REVIEW) is saved so the officer sees
    which rule failed.

    Returns True on success, False if all attempts failed.
    """
    last_error: Exception | None = None

    for attempt in range(_MAX_RULE_RETRIES + 1):
        try:
            _evaluate_and_save(
                review_run_id, rule_id, proposal_id, context, review_model
            )
            return True
        except Exception as e:
            last_error = e
            if attempt < _MAX_RULE_RETRIES:
                if _is_rate_limit_error(e):
                    wait = _RATE_LIMIT_BACKOFF * (attempt + 1)
                else:
                    wait = _RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Rule %s attempt %s failed: %s. Retrying in %ss...",
                    rule_id,
                    attempt + 1,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Rule %s failed after %s attempts: %s",
                    rule_id,
                    attempt + 1,
                    e,
                    exc_info=True,
                )

    _save_error_finding(
        review_run_id=review_run_id,
        rule_id=rule_id,
        proposal_id=proposal_id,
        error=str(last_error),
    )
    return False


def _execute_checklist_import(import_job_id: str) -> None:
    """Core import logic, separated for traceability."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llm
    from onyx.server.features.proposal_review.db import imports as imports_db
    from onyx.server.features.proposal_review.db import rulesets as rulesets_db
    from onyx.server.features.proposal_review.engine.checklist_importer import (
        decompose_checklist_item,
    )
    from onyx.server.features.proposal_review.engine.checklist_importer import (
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
        logger.warning("Import %s: no checklist items found", import_job_id)
        with get_session_with_current_tenant() as db_session:
            job = imports_db.get_import_job(job_uuid, db_session)
            if job:
                job.status = "COMPLETED"
                job.completed_at = datetime.now(timezone.utc)
                db_session.commit()
        return

    # Split items with too many sub-checks into smaller pieces so each
    # LLM call produces bounded output.  The threshold is conservative —
    # 3 sub-checks keeps output well within token limits.
    max_sub_checks = int(
        os.environ.get("PROPOSAL_REVIEW_IMPORT_MAX_SUB_CHECKS_PER_CALL", "3")
    )
    work_items = _split_large_items(items, max_sub_checks)

    logger.info(
        "Import %s: enumerated %s items (%s work units after splitting), "
        "decomposing with %s workers",
        import_job_id,
        len(items),
        len(work_items),
        parallel_workers,
    )

    # Step 3: Decompose each work item in parallel, persist as each completes
    rules_created = 0
    failed_items: list[str] = []
    workers = min(parallel_workers, len(work_items))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_item = {
            executor.submit(
                contextvars.copy_context().run,
                decompose_checklist_item,
                item,
                extracted_text,
                llm,
            ): item
            for item in work_items
        }

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                rule_dicts = cast(list[dict], future.result())
            except Exception as e:
                logger.error(
                    "  [%s] '%s' failed: %s",
                    item.id,
                    item.name,
                    e,
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
                        refinement_needed=rd.get("refinement_needed", False),
                        refinement_question=rd.get("refinement_question"),
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
                "  [%s] '%s': %s rules persisted (%s total)",
                item.id,
                item.name,
                len(rule_dicts),
                rules_created,
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
    logger.info("Import job %s completed: %s", import_job_id, status)


def _mark_import_failed(import_job_id: str, error: str) -> None:
    """Mark an import job as FAILED."""
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
        logger.error("Failed to mark import job %s as FAILED: %s", import_job_id, e)


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
