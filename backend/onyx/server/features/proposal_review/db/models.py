"""SQLAlchemy models for Proposal Review (Argus)."""

import datetime
from uuid import UUID

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import func
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from onyx.db.models import Base


class ProposalReviewRuleset(Base):
    __tablename__ = "proposal_review_ruleset"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    rules: Mapped[list["ProposalReviewRule"]] = relationship(
        "ProposalReviewRule",
        back_populates="ruleset",
        cascade="all, delete-orphan",
        order_by="ProposalReviewRule.priority",
    )


class ProposalReviewRule(Base):
    __tablename__ = "proposal_review_rule"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    ruleset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_ruleset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    rule_intent: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'CHECK'")
    )
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'MANUAL'")
    )
    authority: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_hard_stop: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ruleset: Mapped["ProposalReviewRuleset"] = relationship(
        "ProposalReviewRuleset", back_populates="rules"
    )


class ProposalReviewProposal(Base):
    __tablename__ = "proposal_review_proposal"
    __table_args__ = (
        UniqueConstraint("document_id", "tenant_id"),
        Index("ix_proposal_review_proposal_tenant_id", "tenant_id"),
        Index("ix_proposal_review_proposal_document_id", "document_id"),
        Index("ix_proposal_review_proposal_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    review_runs: Mapped[list["ProposalReviewRun"]] = relationship(
        "ProposalReviewRun",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    findings: Mapped[list["ProposalReviewFinding"]] = relationship(
        "ProposalReviewFinding",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    proposal_decisions: Mapped[list["ProposalReviewProposalDecision"]] = relationship(
        "ProposalReviewProposalDecision",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["ProposalReviewDocument"]] = relationship(
        "ProposalReviewDocument",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["ProposalReviewAuditLog"]] = relationship(
        "ProposalReviewAuditLog",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )


class ProposalReviewRun(Base):
    __tablename__ = "proposal_review_run"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_proposal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ruleset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_ruleset.id"),
        nullable=False,
    )
    triggered_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )
    total_rules: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_rules: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped["ProposalReviewProposal"] = relationship(
        "ProposalReviewProposal", back_populates="review_runs"
    )
    findings: Mapped[list["ProposalReviewFinding"]] = relationship(
        "ProposalReviewFinding",
        back_populates="review_run",
        cascade="all, delete-orphan",
    )


class ProposalReviewFinding(Base):
    __tablename__ = "proposal_review_finding"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_proposal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_rule.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped["ProposalReviewProposal"] = relationship(
        "ProposalReviewProposal", back_populates="findings"
    )
    review_run: Mapped["ProposalReviewRun"] = relationship(
        "ProposalReviewRun", back_populates="findings"
    )
    rule: Mapped["ProposalReviewRule"] = relationship("ProposalReviewRule")
    decision: Mapped["ProposalReviewDecision | None"] = relationship(
        "ProposalReviewDecision",
        back_populates="finding",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ProposalReviewDecision(Base):
    """Officer's decision on a single finding."""

    __tablename__ = "proposal_review_decision"
    __table_args__ = (UniqueConstraint("finding_id"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    finding_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_finding.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    officer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    finding: Mapped["ProposalReviewFinding"] = relationship(
        "ProposalReviewFinding", back_populates="decision"
    )


class ProposalReviewProposalDecision(Base):
    """Officer's final decision on the entire proposal."""

    __tablename__ = "proposal_review_proposal_decision"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_proposal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    officer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    jira_synced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    jira_synced_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped["ProposalReviewProposal"] = relationship(
        "ProposalReviewProposal", back_populates="proposal_decisions"
    )


class ProposalReviewDocument(Base):
    """Manually uploaded documents or auto-fetched FOAs."""

    __tablename__ = "proposal_review_document"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_proposal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_store_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_role: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped["ProposalReviewProposal"] = relationship(
        "ProposalReviewProposal", back_populates="documents"
    )


class ProposalReviewAuditLog(Base):
    """Audit trail for all proposal review actions."""

    __tablename__ = "proposal_review_audit_log"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("proposal_review_proposal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(PGJSONB(), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped["ProposalReviewProposal"] = relationship(
        "ProposalReviewProposal", back_populates="audit_logs"
    )


class ProposalReviewConfig(Base):
    """Admin configuration (one row per tenant)."""

    __tablename__ = "proposal_review_config"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    jira_connector_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jira_project_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_mapping: Mapped[dict | None] = mapped_column(PGJSONB(), nullable=True)
    jira_writeback: Mapped[dict | None] = mapped_column(PGJSONB(), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
