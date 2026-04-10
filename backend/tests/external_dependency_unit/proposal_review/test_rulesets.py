"""Integration tests for ruleset + rule CRUD DB operations."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.proposal_review.db.rulesets import bulk_update_rules
from onyx.server.features.proposal_review.db.rulesets import count_active_rules
from onyx.server.features.proposal_review.db.rulesets import create_rule
from onyx.server.features.proposal_review.db.rulesets import create_ruleset
from onyx.server.features.proposal_review.db.rulesets import delete_rule
from onyx.server.features.proposal_review.db.rulesets import delete_ruleset
from onyx.server.features.proposal_review.db.rulesets import get_rule
from onyx.server.features.proposal_review.db.rulesets import get_ruleset
from onyx.server.features.proposal_review.db.rulesets import list_rules_by_ruleset
from onyx.server.features.proposal_review.db.rulesets import list_rulesets
from onyx.server.features.proposal_review.db.rulesets import update_rule
from onyx.server.features.proposal_review.db.rulesets import update_ruleset
from tests.external_dependency_unit.constants import TEST_TENANT_ID

TENANT = TEST_TENANT_ID


class TestRulesetCRUD:
    def test_create_ruleset_appears_in_list(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Compliance v1 {uuid4().hex[:6]}",
            db_session=db_session,
            description="First ruleset",
            created_by=test_user.id,
        )
        db_session.commit()

        rulesets = list_rulesets(TENANT, db_session)
        ids = [r.id for r in rulesets]
        assert rs.id in ids

    def test_create_ruleset_with_rules_returned_together(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS with rules {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        create_rule(
            ruleset_id=rs.id,
            name="Rule A",
            rule_type="DOCUMENT_CHECK",
            prompt_template="Check A: {{proposal_text}}",
            db_session=db_session,
        )
        create_rule(
            ruleset_id=rs.id,
            name="Rule B",
            rule_type="METADATA_CHECK",
            prompt_template="Check B: {{proposal_text}}",
            db_session=db_session,
        )
        db_session.commit()

        fetched = get_ruleset(rs.id, TENANT, db_session)
        assert fetched is not None
        assert len(fetched.rules) == 2
        rule_names = {r.name for r in fetched.rules}
        assert rule_names == {"Rule A", "Rule B"}

    def test_list_rulesets_active_only_filter(
        self, db_session: Session, test_user: User
    ) -> None:
        rs_active = create_ruleset(
            tenant_id=TENANT,
            name=f"Active RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rs_inactive = create_ruleset(
            tenant_id=TENANT,
            name=f"Inactive RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        update_ruleset(rs_inactive.id, TENANT, db_session, is_active=False)
        db_session.commit()

        active_rulesets = list_rulesets(TENANT, db_session, active_only=True)
        active_ids = {r.id for r in active_rulesets}
        assert rs_active.id in active_ids
        assert rs_inactive.id not in active_ids

    def test_update_ruleset_changes_persist(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Original {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        db_session.commit()

        updated = update_ruleset(
            rs.id,
            TENANT,
            db_session,
            name="Updated Name",
            description="New desc",
        )
        db_session.commit()

        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.description == "New desc"

        refetched = get_ruleset(rs.id, TENANT, db_session)
        assert refetched is not None
        assert refetched.name == "Updated Name"

    def test_update_nonexistent_ruleset_returns_none(self, db_session: Session) -> None:
        result = update_ruleset(uuid4(), TENANT, db_session, name="nope")
        assert result is None

    def test_delete_ruleset_returns_false_for_nonexistent(
        self, db_session: Session
    ) -> None:
        assert delete_ruleset(uuid4(), TENANT, db_session) is False

    def test_set_default_ruleset_clears_previous_default(
        self, db_session: Session, test_user: User
    ) -> None:
        rs1 = create_ruleset(
            tenant_id=TENANT,
            name=f"Default 1 {uuid4().hex[:6]}",
            db_session=db_session,
            is_default=True,
            created_by=test_user.id,
        )
        db_session.commit()
        assert rs1.is_default is True

        rs2 = create_ruleset(
            tenant_id=TENANT,
            name=f"Default 2 {uuid4().hex[:6]}",
            db_session=db_session,
            is_default=True,
            created_by=test_user.id,
        )
        db_session.commit()

        # rs1 should no longer be default
        db_session.refresh(rs1)
        assert rs1.is_default is False
        assert rs2.is_default is True

    def test_delete_ruleset_cascade_deletes_rules(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS to delete {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        r1 = create_rule(
            ruleset_id=rs.id,
            name="Doomed Rule",
            rule_type="DOCUMENT_CHECK",
            prompt_template="{{proposal_text}}",
            db_session=db_session,
        )
        rule_id = r1.id
        db_session.commit()

        assert delete_ruleset(rs.id, TENANT, db_session) is True
        db_session.commit()

        assert get_ruleset(rs.id, TENANT, db_session) is None
        assert get_rule(rule_id, db_session) is None


class TestRuleCRUD:
    def test_create_and_get_rule(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS for rules {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="Budget Cap",
            rule_type="DOCUMENT_CHECK",
            prompt_template="Check budget cap: {{proposal_text}}",
            db_session=db_session,
            description="Verify budget < $1M",
            category="FINANCIAL",
            is_hard_stop=True,
            priority=10,
        )
        db_session.commit()

        fetched = get_rule(rule.id, db_session)
        assert fetched is not None
        assert fetched.name == "Budget Cap"
        assert fetched.rule_type == "DOCUMENT_CHECK"
        assert fetched.is_hard_stop is True
        assert fetched.priority == 10
        assert fetched.category == "FINANCIAL"

    def test_update_rule_prompt_template_and_is_active(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="Rule X",
            rule_type="CUSTOM_NL",
            prompt_template="old template",
            db_session=db_session,
        )
        db_session.commit()
        assert rule.is_active is True

        updated = update_rule(
            rule.id,
            db_session,
            prompt_template="new template: {{proposal_text}}",
            is_active=False,
        )
        db_session.commit()

        assert updated is not None
        assert updated.prompt_template == "new template: {{proposal_text}}"
        assert updated.is_active is False

        refetched = get_rule(rule.id, db_session)
        assert refetched is not None
        assert refetched.prompt_template == "new template: {{proposal_text}}"
        assert refetched.is_active is False

    def test_update_nonexistent_rule_returns_none(self, db_session: Session) -> None:
        result = update_rule(uuid4(), db_session, name="nope")
        assert result is None

    def test_delete_rule(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        rule = create_rule(
            ruleset_id=rs.id,
            name="Temp Rule",
            rule_type="DOCUMENT_CHECK",
            prompt_template="{{proposal_text}}",
            db_session=db_session,
        )
        rule_id = rule.id
        db_session.commit()

        assert delete_rule(rule_id, db_session) is True
        db_session.commit()
        assert get_rule(rule_id, db_session) is None

    def test_delete_nonexistent_rule_returns_false(self, db_session: Session) -> None:
        assert delete_rule(uuid4(), db_session) is False

    def test_list_rules_by_ruleset_respects_active_only(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        r_active = create_rule(
            ruleset_id=rs.id,
            name="Active",
            rule_type="DOCUMENT_CHECK",
            prompt_template="{{proposal_text}}",
            db_session=db_session,
        )
        r_inactive = create_rule(
            ruleset_id=rs.id,
            name="Inactive",
            rule_type="DOCUMENT_CHECK",
            prompt_template="{{proposal_text}}",
            db_session=db_session,
        )
        update_rule(r_inactive.id, db_session, is_active=False)
        db_session.commit()

        all_rules = list_rules_by_ruleset(rs.id, db_session)
        assert len(all_rules) == 2

        active_rules = list_rules_by_ruleset(rs.id, db_session, active_only=True)
        assert len(active_rules) == 1
        assert active_rules[0].id == r_active.id

    def test_bulk_activate_rules_only_affects_specified_rules(
        self, db_session: Session, test_user: User
    ) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Bulk test RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )

        # Create 5 rules, all initially active
        rules = []
        for i in range(5):
            r = create_rule(
                ruleset_id=rs.id,
                name=f"Rule {i}",
                rule_type="DOCUMENT_CHECK",
                prompt_template=f"Template {i}",
                db_session=db_session,
            )
            rules.append(r)
        db_session.commit()

        # Deactivate all 5
        all_ids = [r.id for r in rules]
        bulk_update_rules(all_ids, "deactivate", rs.id, db_session)
        db_session.commit()

        # Verify all are inactive
        assert count_active_rules(rs.id, db_session) == 0

        # Bulk activate only the first 3
        activate_ids = [rules[0].id, rules[1].id, rules[2].id]
        count = bulk_update_rules(activate_ids, "activate", rs.id, db_session)
        db_session.commit()

        assert count == 3
        assert count_active_rules(rs.id, db_session) == 3

        # Verify exactly which are active
        active_rules = list_rules_by_ruleset(rs.id, db_session, active_only=True)
        active_ids_result = {r.id for r in active_rules}
        assert active_ids_result == set(activate_ids)

    def test_bulk_delete_rules(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Bulk delete RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        r1 = create_rule(
            ruleset_id=rs.id,
            name="Keep",
            rule_type="DOCUMENT_CHECK",
            prompt_template="keep",
            db_session=db_session,
        )
        r2 = create_rule(
            ruleset_id=rs.id,
            name="Delete 1",
            rule_type="DOCUMENT_CHECK",
            prompt_template="del1",
            db_session=db_session,
        )
        r3 = create_rule(
            ruleset_id=rs.id,
            name="Delete 2",
            rule_type="DOCUMENT_CHECK",
            prompt_template="del2",
            db_session=db_session,
        )
        db_session.commit()

        count = bulk_update_rules([r2.id, r3.id], "delete", rs.id, db_session)
        db_session.commit()

        assert count == 2
        remaining = list_rules_by_ruleset(rs.id, db_session)
        assert len(remaining) == 1
        assert remaining[0].id == r1.id

    def test_bulk_update_unknown_action_raises_error(self, db_session: Session) -> None:
        import pytest as _pytest

        with _pytest.raises(ValueError, match="Unknown bulk action"):
            bulk_update_rules([uuid4()], "explode", uuid4(), db_session)

    def test_count_active_rules(self, db_session: Session, test_user: User) -> None:
        rs = create_ruleset(
            tenant_id=TENANT,
            name=f"Count RS {uuid4().hex[:6]}",
            db_session=db_session,
            created_by=test_user.id,
        )
        create_rule(
            ruleset_id=rs.id,
            name="Active1",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t1",
            db_session=db_session,
        )
        r2 = create_rule(
            ruleset_id=rs.id,
            name="Inactive1",
            rule_type="DOCUMENT_CHECK",
            prompt_template="t2",
            db_session=db_session,
        )
        update_rule(r2.id, db_session, is_active=False)
        db_session.commit()

        assert count_active_rules(rs.id, db_session) == 1
