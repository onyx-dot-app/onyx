"""Integration tests for review run + findings + progress tracking."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.proposal_review.db.findings import create_finding
from onyx.server.features.proposal_review.db.findings import create_review_run
from onyx.server.features.proposal_review.db.findings import get_finding
from onyx.server.features.proposal_review.db.findings import get_latest_review_run
from onyx.server.features.proposal_review.db.findings import get_review_run
from onyx.server.features.proposal_review.db.findings import (
    list_findings_by_proposal,
)
from onyx.server.features.proposal_review.db.findings import list_findings_by_run
from onyx.server.features.proposal_review.db.proposals import get_or_create_proposal
from onyx.server.features.proposal_review.db.rulesets import create_rule
from onyx.server.features.proposal_review.db.rulesets import create_ruleset
from tests.external_dependency_unit.constants import TEST_TENANT_ID

TENANT = TEST_TENANT_ID


class TestReviewRun:
    def test_create_review_run_and_verify_status(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Review RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        create_rule(
            ruleset_id=rs.id,
            name="Rule 1",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t1",
            db_session=db_session,
        )
        create_rule(
            ruleset_id=rs.id,
            name="Rule 2",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t2",
            db_session=db_session,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        run = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=2,
            db_session=db_session,
        )
        db_session.commit()

        assert run.id is not None
        assert run.proposal_id == proposal.id
        assert run.ruleset_id == rs.id
        assert run.triggered_by == test_user.id
        assert run.total_rules == 2
        assert run.completed_rules == 0
        assert run.status == "PENDING"

    def test_get_review_run(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        run = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        db_session.commit()

        fetched = get_review_run(run.id, db_session)
        assert fetched is not None
        assert fetched.id == run.id

    def test_get_review_run_returns_none_for_nonexistent(
        self, db_session: Session
    ) -> None:
        assert get_review_run(uuid4(), db_session) is None

    def test_get_latest_review_run(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)

        create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        db_session.commit()

        run2 = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=2,
            db_session=db_session,
        )
        db_session.commit()

        latest = get_latest_review_run(proposal.id, db_session)
        assert latest is not None
        assert latest.id == run2.id

    def test_increment_completed_rules_tracks_progress(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Progress RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        run = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=3,
            db_session=db_session,
        )
        db_session.commit()

        # Simulate progress by incrementing completed_rules directly
        run.completed_rules = 1
        db_session.flush()
        db_session.commit()

        fetched = get_review_run(run.id, db_session)
        assert fetched is not None
        assert fetched.completed_rules == 1
        assert fetched.total_rules == 3

        run.completed_rules = 3
        db_session.flush()
        db_session.commit()

        fetched = get_review_run(run.id, db_session)
        assert fetched is not None
        assert fetched.completed_rules == 3


class TestFindings:
    def test_create_finding_and_retrieve(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Findings RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="Budget Rule",
            rule_type="DOCUMENT_CHECK",
            prompt_template="Check budget",
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
        db_session.commit()

        finding = create_finding(
            proposal_id=proposal.id,
            rule_id=rule.id,
            review_run_id=run.id,
            verdict="PASS",
            db_session=db_session,
            confidence="HIGH",
            evidence="Budget is $500k",
            explanation="Under the $1M cap",
            llm_model="gpt-4",
            llm_tokens_used=1500,
        )
        db_session.commit()

        fetched = get_finding(finding.id, db_session)
        assert fetched is not None
        assert fetched.verdict == "PASS"
        assert fetched.confidence == "HIGH"
        assert fetched.evidence == "Budget is $500k"
        assert fetched.llm_model == "gpt-4"
        assert fetched.llm_tokens_used == 1500
        assert fetched.rule is not None
        assert fetched.rule.name == "Budget Rule"

    def test_list_findings_by_proposal(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"List Findings RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule1 = create_rule(
            ruleset_id=rs.id,
            name="R1",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t1",
            db_session=db_session,
        )
        rule2 = create_rule(
            ruleset_id=rs.id,
            name="R2",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t2",
            db_session=db_session,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        run = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=2,
            db_session=db_session,
        )
        db_session.commit()

        create_finding(
            proposal_id=proposal.id,
            rule_id=rule1.id,
            review_run_id=run.id,
            verdict="PASS",
            db_session=db_session,
        )
        create_finding(
            proposal_id=proposal.id,
            rule_id=rule2.id,
            review_run_id=run.id,
            verdict="FAIL",
            db_session=db_session,
        )
        db_session.commit()

        findings = list_findings_by_proposal(proposal.id, db_session)
        assert len(findings) == 2
        verdicts = {f.verdict for f in findings}
        assert verdicts == {"PASS", "FAIL"}

    def test_list_findings_by_run_filters_correctly(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Run Filter RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="R",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t",
            db_session=db_session,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        run1 = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        run2 = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        db_session.commit()

        create_finding(
            proposal_id=proposal.id,
            rule_id=rule.id,
            review_run_id=run1.id,
            verdict="PASS",
            db_session=db_session,
        )
        create_finding(
            proposal_id=proposal.id,
            rule_id=rule.id,
            review_run_id=run2.id,
            verdict="FAIL",
            db_session=db_session,
        )
        db_session.commit()

        run1_findings = list_findings_by_run(run1.id, db_session)
        assert len(run1_findings) == 1
        assert run1_findings[0].verdict == "PASS"

        run2_findings = list_findings_by_run(run2.id, db_session)
        assert len(run2_findings) == 1
        assert run2_findings[0].verdict == "FAIL"

    def test_list_findings_by_proposal_with_run_id_filter(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Filter RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="R",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t",
            db_session=db_session,
        )
        proposal = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        run1 = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        run2 = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=1,
            db_session=db_session,
        )
        db_session.commit()

        create_finding(
            proposal_id=proposal.id,
            rule_id=rule.id,
            review_run_id=run1.id,
            verdict="PASS",
            db_session=db_session,
        )
        create_finding(
            proposal_id=proposal.id,
            rule_id=rule.id,
            review_run_id=run2.id,
            verdict="FAIL",
            db_session=db_session,
        )
        db_session.commit()

        # All findings for proposal
        all_findings = list_findings_by_proposal(proposal.id, db_session)
        assert len(all_findings) == 2

        # Filtered by run
        filtered = list_findings_by_proposal(
            proposal.id, db_session, review_run_id=run1.id
        )
        assert len(filtered) == 1
        assert filtered[0].verdict == "PASS"

    def test_get_finding_returns_none_for_nonexistent(
        self, db_session: Session
    ) -> None:
        assert get_finding(uuid4(), db_session) is None

    def test_full_review_flow_end_to_end(
        self, db_session: Session, test_user: User
    ) -> None:
        """Create ruleset with rules -> proposal -> run -> findings -> verify."""
        # Setup
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"E2E RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rules = []
        for i in range(3):
            r = create_rule(
                ruleset_id=rs.id,
                name=f"E2E Rule {i}",
                rule_type="DOCUMENT_CHECK",
                prompt_template=f"Check {i}: {{{{proposal_text}}}}",
                db_session=db_session,
            )
            rules.append(r)

        proposal = get_or_create_proposal(
            f"doc-e2e-{uuid4().hex[:8]}", TENANT, db_session
        )
        run = create_review_run(
            proposal_id=proposal.id,
            ruleset_id=rs.id,
            triggered_by=test_user.id,
            total_rules=3,
            db_session=db_session,
        )
        db_session.commit()

        # Create findings for each rule
        verdicts = ["PASS", "FAIL", "PASS"]
        for rule, verdict in zip(rules, verdicts):
            create_finding(
                proposal_id=proposal.id,
                rule_id=rule.id,
                review_run_id=run.id,
                verdict=verdict,
                db_session=db_session,
                confidence="HIGH",
            )
            run.completed_rules += 1
        db_session.flush()
        db_session.commit()

        # Verify
        fetched_run = get_review_run(run.id, db_session)
        assert fetched_run is not None
        assert fetched_run.completed_rules == 3
        assert fetched_run.total_rules == 3

        findings = list_findings_by_run(run.id, db_session)
        assert len(findings) == 3
        assert {f.verdict for f in findings} == {"PASS", "FAIL"}
