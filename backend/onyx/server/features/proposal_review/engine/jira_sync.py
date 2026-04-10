"""Writes officer decisions back to Jira."""

from datetime import datetime
from datetime import timezone
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import (
    fetch_connector_credential_pair_for_connector,
)
from onyx.db.models import Document
from onyx.server.features.proposal_review.db import config as config_db
from onyx.server.features.proposal_review.db import decisions as decisions_db
from onyx.server.features.proposal_review.db import findings as findings_db
from onyx.server.features.proposal_review.db import proposals as proposals_db
from onyx.server.features.proposal_review.db.models import ProposalReviewFinding
from onyx.server.features.proposal_review.db.models import (
    ProposalReviewProposalDecision,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def sync_to_jira(
    proposal_id: UUID,
    db_session: Session,
) -> None:
    """Write the officer's final decision back to Jira.

    Performs up to 3 Jira API operations:
    1. PUT custom fields (decision, completion %)
    2. POST transition (move to configured column)
    3. POST comment (structured review summary)

    Then marks the decision as jira_synced.

    Raises:
        ValueError: If required config/data is missing.
        RuntimeError: If Jira API calls fail.
    """
    tenant_id = get_current_tenant_id()

    # Load proposal and decision
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")

    latest_decision = decisions_db.get_latest_proposal_decision(proposal_id, db_session)
    if not latest_decision:
        raise ValueError(f"No decision found for proposal {proposal_id}")

    if latest_decision.jira_synced:
        logger.info(f"Decision for proposal {proposal_id} already synced to Jira")
        return

    # Load tenant config for Jira settings
    config = config_db.get_config(tenant_id, db_session)
    if not config:
        raise ValueError("Proposal review config not found for this tenant")

    if not config.jira_connector_id:
        raise ValueError(
            "No Jira connector configured. Set jira_connector_id in proposal review settings."
        )

    writeback_config = config.jira_writeback or {}

    # Get the Jira issue key from the linked Document
    parent_doc = (
        db_session.query(Document)
        .filter(Document.id == proposal.document_id)
        .one_or_none()
    )
    if not parent_doc:
        raise ValueError(f"Linked document {proposal.document_id} not found")

    # semantic_id is formatted as "KEY-123: Summary text" by the Jira connector.
    # Extract just the issue key (everything before the first colon).
    raw_id = parent_doc.semantic_id
    if not raw_id:
        raise ValueError(
            f"Document {proposal.document_id} has no semantic_id (Jira issue key)"
        )
    issue_key = raw_id.split(":")[0].strip()

    # Get Jira credentials from the connector
    jira_base_url, auth_headers = _get_jira_credentials(
        config.jira_connector_id, db_session
    )

    # Get findings for the summary
    latest_run = findings_db.get_latest_review_run(proposal_id, db_session)
    all_findings: list[ProposalReviewFinding] = []
    if latest_run:
        all_findings = findings_db.list_findings_by_run(latest_run.id, db_session)

    # Calculate summary counts
    verdict_counts = _count_verdicts(all_findings)

    # Operation 1: Update custom fields
    _update_custom_fields(
        jira_base_url=jira_base_url,
        auth_headers=auth_headers,
        issue_key=issue_key,
        decision=latest_decision.decision,
        verdict_counts=verdict_counts,
        writeback_config=writeback_config,
    )

    # Operation 2: Transition the issue
    _transition_issue(
        jira_base_url=jira_base_url,
        auth_headers=auth_headers,
        issue_key=issue_key,
        decision=latest_decision.decision,
        writeback_config=writeback_config,
    )

    # Operation 3: Post review summary comment
    _post_comment(
        jira_base_url=jira_base_url,
        auth_headers=auth_headers,
        issue_key=issue_key,
        decision=latest_decision,
        verdict_counts=verdict_counts,
        findings=all_findings,
    )

    # Mark the decision as synced
    decisions_db.mark_decision_jira_synced(latest_decision.id, db_session)
    db_session.flush()

    logger.info(
        f"Successfully synced decision for proposal {proposal_id} to Jira issue {issue_key}"
    )


def _get_jira_credentials(
    connector_id: int,
    db_session: Session,
) -> tuple[str, dict[str, str]]:
    """Extract Jira base URL and auth headers from the connector's credentials.

    Returns:
        Tuple of (jira_base_url, auth_headers_dict).
    """
    connector = fetch_connector_by_id(connector_id, db_session)
    if not connector:
        raise ValueError(f"Jira connector {connector_id} not found")

    # Get the connector's credential pair
    cc_pair = fetch_connector_credential_pair_for_connector(db_session, connector_id)
    if not cc_pair:
        raise ValueError(f"No credential pair found for connector {connector_id}")

    # Extract credentials — guard against missing credential_json
    cred_json = cc_pair.credential.credential_json
    if cred_json is None:
        raise ValueError(f"No credential_json for connector {connector_id}")
    credentials = cred_json.get_value(apply_mask=False)
    if not credentials:
        raise ValueError(f"Empty credentials for connector {connector_id}")

    # Extract Jira base URL from connector config
    connector_config = connector.connector_specific_config or {}
    jira_base_url = connector_config.get("jira_project_url", "")
    if jira_base_url:
        # The connector stores the full project URL; extract base
        from urllib.parse import urlparse

        parsed = urlparse(jira_base_url)
        jira_base_url = f"{parsed.scheme}://{parsed.netloc}"

    if not jira_base_url:
        raise ValueError("Could not determine Jira base URL from connector config")

    # Build auth headers
    api_token = credentials.get("jira_api_token", "")
    email = credentials.get("jira_user_email")

    if email:
        # Cloud auth: Basic auth with email:token
        import base64

        auth_string = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        auth_headers = {
            "Authorization": f"Basic {auth_string}",
            "Content-Type": "application/json",
        }
    else:
        # Server auth: Bearer token
        auth_headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    return jira_base_url, auth_headers


def _count_verdicts(findings: list[ProposalReviewFinding]) -> dict[str, int]:
    """Count findings by verdict."""
    counts: dict[str, int] = {
        "PASS": 0,
        "FAIL": 0,
        "FLAG": 0,
        "NEEDS_REVIEW": 0,
        "NOT_APPLICABLE": 0,
    }
    for f in findings:
        verdict = f.verdict.upper() if f.verdict else "NEEDS_REVIEW"
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def _update_custom_fields(
    jira_base_url: str,
    auth_headers: dict[str, str],
    issue_key: str,
    decision: str,
    verdict_counts: dict[str, int],
    writeback_config: dict,
) -> None:
    """PUT custom fields on the Jira issue (decision, completion %)."""
    decision_field = writeback_config.get("decision_field_id")
    completion_field = writeback_config.get("completion_field_id")

    if not decision_field and not completion_field:
        logger.debug("No custom field IDs configured for Jira writeback, skipping")
        return

    fields: dict = {}
    if decision_field:
        fields[decision_field] = decision
    if completion_field:
        total = sum(verdict_counts.values())
        completed = total - verdict_counts.get("NEEDS_REVIEW", 0)
        pct = (completed / total * 100) if total > 0 else 0
        fields[completion_field] = round(pct, 1)

    url = f"{jira_base_url}/rest/api/3/issue/{issue_key}"
    payload = {"fields": fields}

    try:
        resp = requests.put(url, headers=auth_headers, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info(f"Updated custom fields on {issue_key}")
    except requests.RequestException as e:
        logger.error(f"Failed to update custom fields on {issue_key}: {e}")
        raise RuntimeError(f"Jira field update failed: {e}") from e


def _transition_issue(
    jira_base_url: str,
    auth_headers: dict[str, str],
    issue_key: str,
    decision: str,
    writeback_config: dict,
) -> None:
    """POST a transition to move the issue to the appropriate column."""
    transition_map = writeback_config.get("transitions", {})
    transition_name = transition_map.get(decision)

    if not transition_name:
        logger.debug(f"No transition configured for decision '{decision}', skipping")
        return

    # First, get available transitions
    transitions_url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/transitions"
    try:
        resp = requests.get(transitions_url, headers=auth_headers, timeout=30)
        resp.raise_for_status()
        available = resp.json().get("transitions", [])
    except requests.RequestException as e:
        logger.error(f"Failed to fetch transitions for {issue_key}: {e}")
        raise RuntimeError(f"Jira transition fetch failed: {e}") from e

    # Find the matching transition by name (case-insensitive)
    target_transition = None
    for t in available:
        if t.get("name", "").lower() == transition_name.lower():
            target_transition = t
            break

    if not target_transition:
        available_names = [t.get("name", "") for t in available]
        logger.warning(
            f"Transition '{transition_name}' not found for {issue_key}. "
            f"Available: {available_names}"
        )
        return

    # Perform the transition
    payload = {"transition": {"id": target_transition["id"]}}
    try:
        resp = requests.post(
            transitions_url, headers=auth_headers, json=payload, timeout=30
        )
        resp.raise_for_status()
        logger.info(f"Transitioned {issue_key} to '{transition_name}'")
    except requests.RequestException as e:
        logger.error(f"Failed to transition {issue_key}: {e}")
        raise RuntimeError(f"Jira transition failed: {e}") from e


def _post_comment(
    jira_base_url: str,
    auth_headers: dict[str, str],
    issue_key: str,
    decision: ProposalReviewProposalDecision | None,
    verdict_counts: dict[str, int],
    findings: list[ProposalReviewFinding],
) -> None:
    """POST a structured review summary as a Jira comment."""
    comment_text = _build_comment_text(decision, verdict_counts, findings)

    url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/comment"
    # Jira Cloud uses ADF (Atlassian Document Format) for comments
    payload = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": comment_text,
                        }
                    ],
                }
            ],
        }
    }

    try:
        resp = requests.post(url, headers=auth_headers, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info(f"Posted review summary comment on {issue_key}")
    except requests.RequestException as e:
        logger.error(f"Failed to post comment on {issue_key}: {e}")
        raise RuntimeError(f"Jira comment post failed: {e}") from e


def _build_comment_text(
    decision: ProposalReviewProposalDecision | None,
    verdict_counts: dict[str, int],
    findings: list[ProposalReviewFinding],
) -> str:
    """Build a structured review summary text for the Jira comment."""
    lines: list[str] = []

    lines.append("=== Argus Proposal Review Summary ===")
    lines.append("")

    # Decision
    decision_text = getattr(decision, "decision", "N/A")
    decision_notes = getattr(decision, "notes", None)
    lines.append(f"Final Decision: {decision_text}")
    if decision_notes:
        lines.append(f"Notes: {decision_notes}")
    lines.append("")

    # Summary counts
    total = sum(verdict_counts.values())
    lines.append(f"Review Results ({total} rules evaluated):")
    lines.append(f"  Pass: {verdict_counts.get('PASS', 0)}")
    lines.append(f"  Fail: {verdict_counts.get('FAIL', 0)}")
    lines.append(f"  Flag: {verdict_counts.get('FLAG', 0)}")
    lines.append(f"  Needs Review: {verdict_counts.get('NEEDS_REVIEW', 0)}")
    lines.append(f"  Not Applicable: {verdict_counts.get('NOT_APPLICABLE', 0)}")
    lines.append("")

    # Individual findings (truncated for readability)
    if findings:
        lines.append("--- Detailed Findings ---")
        for f in findings:
            rule_name = f.rule.name if f.rule else "Unknown Rule"
            verdict = f.verdict or "N/A"
            officer_action = ""
            if f.decision:
                officer_action = f" | Officer: {f.decision.action}"
            lines.append(f"  [{verdict}] {rule_name}{officer_action}")
            if f.explanation:
                # Truncate long explanations
                explanation = f.explanation[:200]
                if len(f.explanation) > 200:
                    explanation += "..."
                lines.append(f"    Reason: {explanation}")

    lines.append("")
    lines.append(f"Reviewed at: {datetime.now(timezone.utc).isoformat()}")
    lines.append("Generated by Argus (Onyx Proposal Review)")

    return "\n".join(lines)
