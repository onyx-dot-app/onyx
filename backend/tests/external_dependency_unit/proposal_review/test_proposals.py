"""Integration tests for proposal state management DB operations."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.proposals import count_proposals
from onyx.server.features.proposal_review.db.proposals import get_or_create_proposal
from onyx.server.features.proposal_review.db.proposals import get_proposal
from onyx.server.features.proposal_review.db.proposals import (
    get_proposal_by_document_id,
)
from onyx.server.features.proposal_review.db.proposals import list_proposals
from onyx.server.features.proposal_review.db.proposals import update_proposal_status
from tests.external_dependency_unit.constants import TEST_TENANT_ID

TENANT = TEST_TENANT_ID


class TestGetOrCreateProposal:
    def test_creates_proposal_on_first_call(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        proposal = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        assert proposal.id is not None
        assert proposal.document_id == doc_id
        assert proposal.tenant_id == TENANT
        assert proposal.status == "PENDING"

    def test_returns_same_proposal_on_second_call(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        first = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        second = get_or_create_proposal(doc_id, TENANT, db_session)
        assert second.id == first.id

    def test_different_document_ids_create_different_proposals(
        self, db_session: Session
    ) -> None:
        p1 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        p2 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        assert p1.id != p2.id


class TestGetProposal:
    def test_returns_none_for_nonexistent_id(self, db_session: Session) -> None:
        result = get_proposal(uuid4(), TENANT, db_session)
        assert result is None

    def test_returns_proposal_by_id(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        created = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        fetched = get_proposal(created.id, TENANT, db_session)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.document_id == doc_id

    def test_returns_none_for_wrong_tenant(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        created = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        result = get_proposal(created.id, "nonexistent_tenant", db_session)
        assert result is None


class TestGetProposalByDocumentId:
    def test_returns_none_when_no_proposal_exists(self, db_session: Session) -> None:
        result = get_proposal_by_document_id("no-such-doc", TENANT, db_session)
        assert result is None

    def test_finds_proposal_by_document_id(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        created = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        fetched = get_proposal_by_document_id(doc_id, TENANT, db_session)
        assert fetched is not None
        assert fetched.id == created.id


class TestUpdateProposalStatus:
    def test_changes_status_correctly(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        proposal = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()
        assert proposal.status == "PENDING"

        updated = update_proposal_status(proposal.id, TENANT, "IN_REVIEW", db_session)
        db_session.commit()

        assert updated is not None
        assert updated.status == "IN_REVIEW"

        # Verify persisted
        refetched = get_proposal(proposal.id, TENANT, db_session)
        assert refetched is not None
        assert refetched.status == "IN_REVIEW"

    def test_returns_none_for_nonexistent_proposal(self, db_session: Session) -> None:
        result = update_proposal_status(uuid4(), TENANT, "IN_REVIEW", db_session)
        assert result is None

    def test_successive_status_updates(self, db_session: Session) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        proposal = get_or_create_proposal(doc_id, TENANT, db_session)
        db_session.commit()

        update_proposal_status(proposal.id, TENANT, "IN_REVIEW", db_session)
        db_session.commit()
        update_proposal_status(proposal.id, TENANT, "APPROVED", db_session)
        db_session.commit()

        refetched = get_proposal(proposal.id, TENANT, db_session)
        assert refetched is not None
        assert refetched.status == "APPROVED"


class TestListAndCountProposals:
    def test_list_proposals_with_status_filter(self, db_session: Session) -> None:
        p1 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        p2 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        update_proposal_status(p1.id, TENANT, "IN_REVIEW", db_session)
        db_session.commit()

        in_review = list_proposals(TENANT, db_session, status="IN_REVIEW")
        in_review_ids = {p.id for p in in_review}
        assert p1.id in in_review_ids
        assert p2.id not in in_review_ids

    def test_count_proposals_with_status_filter(self, db_session: Session) -> None:
        p1 = get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        update_proposal_status(p1.id, TENANT, "COMPLETED", db_session)
        db_session.commit()

        total = count_proposals(TENANT, db_session)
        completed = count_proposals(TENANT, db_session, status="COMPLETED")

        assert total >= 2
        assert completed >= 1

    def test_list_proposals_pagination(self, db_session: Session) -> None:
        for _ in range(5):
            get_or_create_proposal(f"doc-{uuid4().hex[:8]}", TENANT, db_session)
        db_session.commit()

        page = list_proposals(TENANT, db_session, limit=2, offset=0)
        assert len(page) <= 2
