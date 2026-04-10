"""Integration tests for per-finding decisions, proposal decisions, config, and audit log."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.proposal_review.db.config import get_config
from onyx.server.features.proposal_review.db.config import upsert_config
from onyx.server.features.proposal_review.db.decisions import create_audit_log
from onyx.server.features.proposal_review.db.decisions import (
    create_proposal_decision,
)
from onyx.server.features.proposal_review.db.decisions import get_finding_decision
from onyx.server.features.proposal_review.db.decisions import (
    get_latest_proposal_decision,
)
from onyx.server.features.proposal_review.db.decisions import list_audit_log
from onyx.server.features.proposal_review.db.decisions import (
    mark_decision_jira_synced,
)
from onyx.server.features.proposal_review.db.decisions import (
    upsert_finding_decision,
)
from onyx.server.features.proposal_review.db.findings import create_finding
from onyx.server.features.proposal_review.db.findings import create_review_run
from onyx.server.features.proposal_review.db.findings import get_finding
from onyx.server.features.proposal_review.db.proposals import get_or_create_proposal
from onyx.server.features.proposal_review.db.proposals import update_proposal_status
from onyx.server.features.proposal_review.db.rulesets import create_rule
from onyx.server.features.proposal_review.db.rulesets import create_ruleset
from tests.external_dependency_unit.constants import TEST_TENANT_ID

TENANT = TEST_TENANT_ID


def _make_finding(db_session: Session, test_user: User):
    """Helper: create a full chain (ruleset -> rule -> proposal -> run -> finding)."""
    rs = create_ruleset(
        tenant_id=TENANT,
        name=f"RS-{uuid4().hex[:6]}",
        db_session=db_session,
        created_by=test_user.id,
    )
    rule = create_rule(
        ruleset_id=rs.id,
        name="Test Rule",
        rule_type="DOCUMENT_CHECK",
        prompt_template="{{proposal_text}}",
        db_session=db_session,
    )
    proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
    run = create_review_run(
        proposal_id=proposal.id,
        ruleset_id=rs.id,
        triggered_by=test_user.id,
        total_rules=1,
        db_session=db_session,
    )
    finding = create_finding(
        proposal_id=proposal.id,
        rule_id=rule.id,
        review_run_id=run.id,
        verdict="FAIL",
        db_session=db_session,
    )
    db_session.commit()
    return finding, proposal


class TestFindingDecision:
    def test_create_finding_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)

        decision = upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="VERIFIED",
            db_session=db_session,
            notes="Looks good",
        )
        db_session.commit()

        assert decision.id is not None
        assert decision.finding_id == finding.id
        assert decision.action == "VERIFIED"
        assert decision.notes == "Looks good"

    def test_upsert_overwrites_previous_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)

        first = upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="VERIFIED",
            db_session=db_session,
        )
        db_session.commit()
        first_id = first.id

        second = upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="ISSUE",
            db_session=db_session,
            notes="Actually, this is a problem",
        )
        db_session.commit()

        # Same row was updated, not a new one created
        assert second.id == first_id
        assert second.action == "ISSUE"
        assert second.notes == "Actually, this is a problem"

    def test_get_finding_decision(self, db_session: Session, test_user: User) -> None:
        finding, _ = _make_finding(db_session, test_user)

        upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="NOT_APPLICABLE",
            db_session=db_session,
        )
        db_session.commit()

        fetched = get_finding_decision(finding.id, db_session)
        assert fetched is not None
        assert fetched.action == "NOT_APPLICABLE"

    def test_get_finding_decision_returns_none_when_no_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)
        assert get_finding_decision(finding.id, db_session) is None

    def test_finding_decision_accessible_via_finding_relationship(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)

        upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="OVERRIDDEN",
            db_session=db_session,
        )
        db_session.commit()

        fetched = get_finding(finding.id, db_session)
        assert fetched is not None
        assert fetched.decision is not None
        assert fetched.decision.action == "OVERRIDDEN"


class TestProposalDecision:
    def test_create_proposal_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        pd = create_proposal_decision(
            proposal_id=proposal.id,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
            notes="All checks pass",
        )
        db_session.commit()

        assert pd.id is not None
        assert pd.decision == "APPROVED"
        assert pd.notes == "All checks pass"
        assert pd.jira_synced is False

    def test_get_latest_proposal_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        create_proposal_decision(
            proposal_id=proposal.id,
            officer_id=test_user.id,
            decision="CHANGES_REQUESTED",
            db_session=db_session,
        )
        db_session.commit()

        create_proposal_decision(
            proposal_id=proposal.id,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
        )
        db_session.commit()

        latest = get_latest_proposal_decision(proposal.id, db_session)
        assert latest is not None
        assert latest.decision == "APPROVED"

    def test_get_latest_proposal_decision_returns_none_when_empty(
        self, db_session: Session
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        assert get_latest_proposal_decision(proposal.id, db_session) is None

    def test_proposal_decision_updates_proposal_status(
        self, db_session: Session, test_user: User
    ) -> None:
        """Verify that recording a decision and updating status works together."""
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        create_proposal_decision(
            proposal_id=proposal.id,
            officer_id=test_user.id,
            decision="REJECTED",
            db_session=db_session,
        )
        update_proposal_status(proposal.id, TENANT, "REJECTED", db_session)
        db_session.commit()

        db_session.refresh(proposal)
        assert proposal.status == "REJECTED"

    def test_mark_decision_jira_synced(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        pd = create_proposal_decision(
            proposal_id=proposal.id,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
        )
        db_session.commit()

        assert pd.jira_synced is False

        synced = mark_decision_jira_synced(pd.id, db_session)
        db_session.commit()

        assert synced is not None
        assert synced.jira_synced is True
        assert synced.jira_synced_at is not None

    def test_mark_decision_jira_synced_returns_none_for_nonexistent(
        self, db_session: Session
    ) -> None:
        assert mark_decision_jira_synced(uuid4(), db_session) is None


class TestConfig:
    def test_create_config(self, db_session: Session) -> None:
        # Use a unique tenant to avoid collision with other tests
        tenant = f"test-tenant-{uuid4().hex[:8]}"
        config = upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            jira_project_key="PROJ",
            field_mapping={"title": "summary", "budget": "customfield_10001"},
        )
        db_session.commit()

        assert config.id is not None
        assert config.tenant_id == tenant
        assert config.jira_project_key == "PROJ"
        assert config.field_mapping == {
            "title": "summary",
            "budget": "customfield_10001",
        }

    def test_upsert_config_updates_existing(self, db_session: Session) -> None:
        tenant = f"test-tenant-{uuid4().hex[:8]}"
        first = upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            jira_project_key="OLD",
        )
        db_session.commit()
        first_id = first.id

        second = upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            jira_project_key="NEW",
            field_mapping={"x": "y"},
        )
        db_session.commit()

        assert second.id == first_id
        assert second.jira_project_key == "NEW"
        assert second.field_mapping == {"x": "y"}

    def test_get_config_returns_correct_tenant(self, db_session: Session) -> None:
        tenant = f"test-tenant-{uuid4().hex[:8]}"
        upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            jira_project_key="ABC",
            jira_writeback={"status_field": "customfield_20001"},
        )
        db_session.commit()

        fetched = get_config(tenant, db_session)
        assert fetched is not None
        assert fetched.jira_project_key == "ABC"
        assert fetched.jira_writeback == {"status_field": "customfield_20001"}

    def test_get_config_returns_none_for_unknown_tenant(
        self, db_session: Session
    ) -> None:
        assert get_config(f"nonexistent-{uuid4().hex[:8]}", db_session) is None

    def test_upsert_config_preserves_unset_fields(self, db_session: Session) -> None:
        tenant = f"test-tenant-{uuid4().hex[:8]}"
        upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            jira_project_key="KEEP",
            jira_connector_id=42,
        )
        db_session.commit()

        # Update only field_mapping, leave jira_project_key alone
        upsert_config(
            tenant_id=tenant,
            db_session=db_session,
            field_mapping={"a": "b"},
        )
        db_session.commit()

        fetched = get_config(tenant, db_session)
        assert fetched is not None
        assert fetched.jira_project_key == "KEEP"
        assert fetched.jira_connector_id == 42
        assert fetched.field_mapping == {"a": "b"}


class TestAuditLog:
    def test_create_audit_log_entry(self, db_session: Session, test_user: User) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        entry = create_audit_log(
            proposal_id=proposal.id,
            action="REVIEW_STARTED",
            db_session=db_session,
            user_id=test_user.id,
            details={"ruleset_id": str(uuid4())},
        )
        db_session.commit()

        assert entry.id is not None
        assert entry.action == "REVIEW_STARTED"
        assert entry.user_id == test_user.id

    def test_list_audit_log_ordered_by_created_at_desc(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        actions = ["REVIEW_STARTED", "FINDING_CREATED", "DECISION_MADE"]
        for action in actions:
            create_audit_log(
                proposal_id=proposal.id,
                action=action,
                db_session=db_session,
                user_id=test_user.id,
            )
            db_session.commit()

        entries = list_audit_log(proposal.id, db_session)
        assert len(entries) == 3
        # Newest first
        assert entries[0].action == "DECISION_MADE"
        assert entries[1].action == "FINDING_CREATED"
        assert entries[2].action == "REVIEW_STARTED"

    def test_audit_log_entries_are_scoped_to_proposal(
        self, db_session: Session, test_user: User  # noqa: ARG002
    ) -> None:
        p1 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        p2 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        create_audit_log(
            proposal_id=p1.id,
            action="ACTION_A",
            db_session=db_session,
        )
        create_audit_log(
            proposal_id=p2.id,
            action="ACTION_B",
            db_session=db_session,
        )
        db_session.commit()

        p1_entries = list_audit_log(p1.id, db_session)
        p1_actions = {e.action for e in p1_entries}
        assert "ACTION_A" in p1_actions
        assert "ACTION_B" not in p1_actions

    def test_audit_log_with_null_user_id(self, db_session: Session) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        entry = create_audit_log(
            proposal_id=proposal.id,
            action="SYSTEM_ACTION",
            db_session=db_session,
            details={"source": "automated"},
        )
        db_session.commit()

        assert entry.user_id is None
        assert entry.details == {"source": "automated"}
