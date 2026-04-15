"""Integration tests for per-finding decisions, proposal decisions, and config."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.proposal_review.db.config import get_config
from onyx.server.features.proposal_review.db.config import upsert_config
from onyx.server.features.proposal_review.db.decisions import (
    mark_proposal_jira_synced,
)
from onyx.server.features.proposal_review.db.decisions import (
    update_proposal_decision,
)
from onyx.server.features.proposal_review.db.decisions import (
    upsert_finding_decision,
)
from onyx.server.features.proposal_review.db.findings import create_finding
from onyx.server.features.proposal_review.db.findings import create_review_run
from onyx.server.features.proposal_review.db.findings import get_finding
from onyx.server.features.proposal_review.db.proposals import get_or_create_proposal
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

        updated = upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="VERIFIED",
            db_session=db_session,
            notes="Looks good",
        )
        db_session.commit()

        assert updated.id == finding.id
        assert updated.decision_action == "VERIFIED"
        assert updated.decision_notes == "Looks good"
        assert updated.decided_at is not None

    def test_upsert_overwrites_previous_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)

        upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="VERIFIED",
            db_session=db_session,
        )
        db_session.commit()

        updated = upsert_finding_decision(
            finding_id=finding.id,
            officer_id=test_user.id,
            action="ISSUE",
            db_session=db_session,
            notes="Actually, this is a problem",
        )
        db_session.commit()

        # Same row was updated
        assert updated.id == finding.id
        assert updated.decision_action == "ISSUE"
        assert updated.decision_notes == "Actually, this is a problem"

    def test_finding_decision_accessible_via_finding(
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
        assert fetched.decision_action == "OVERRIDDEN"
        assert fetched.decision_officer_id == test_user.id

    def test_finding_has_no_decision_by_default(
        self, db_session: Session, test_user: User
    ) -> None:
        finding, _ = _make_finding(db_session, test_user)
        assert finding.decision_action is None
        assert finding.decided_at is None


class TestProposalDecision:
    def test_update_proposal_decision(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        updated = update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
            notes="All checks pass",
        )
        db_session.commit()

        assert updated.status == "APPROVED"
        assert updated.decision_notes == "All checks pass"
        assert updated.decision_officer_id == test_user.id
        assert updated.decision_at is not None
        assert updated.jira_synced is False

    def test_proposal_decision_overwrites_previous(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="CHANGES_REQUESTED",
            db_session=db_session,
        )
        db_session.commit()

        updated = update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
        )
        db_session.commit()

        assert updated.status == "APPROVED"

    def test_mark_proposal_jira_synced(
        self, db_session: Session, test_user: User
    ) -> None:
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
        )
        db_session.commit()

        assert proposal.jira_synced is False

        synced = mark_proposal_jira_synced(proposal.id, TENANT, db_session)
        db_session.commit()

        assert synced is not None
        assert synced.jira_synced is True
        assert synced.jira_synced_at is not None

    def test_mark_jira_synced_returns_none_for_nonexistent(
        self, db_session: Session
    ) -> None:
        assert mark_proposal_jira_synced(uuid4(), TENANT, db_session) is None

    def test_new_decision_resets_jira_synced(
        self, db_session: Session, test_user: User
    ) -> None:
        """Re-deciding should reset jira_synced so the new decision can be synced."""
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="APPROVED",
            db_session=db_session,
        )
        mark_proposal_jira_synced(proposal.id, TENANT, db_session)
        db_session.commit()
        assert proposal.jira_synced is True

        update_proposal_decision(
            proposal_id=proposal.id,
            tenant_id=TENANT,
            officer_id=test_user.id,
            decision="REJECTED",
            db_session=db_session,
        )
        db_session.commit()

        db_session.refresh(proposal)
        assert proposal.jira_synced is False
        assert proposal.jira_synced_at is None
        assert proposal.status == "REJECTED"


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
