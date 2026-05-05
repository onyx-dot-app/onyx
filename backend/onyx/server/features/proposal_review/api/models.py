"""Pydantic request/response models for Proposal Review."""

from datetime import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from onyx.server.features.proposal_review.db.models import ProposalReviewConfig
from onyx.server.features.proposal_review.db.models import ProposalReviewDocument
from onyx.server.features.proposal_review.db.models import ProposalReviewFinding
from onyx.server.features.proposal_review.db.models import ProposalReviewImportJob
from onyx.server.features.proposal_review.db.models import ProposalReviewProposal
from onyx.server.features.proposal_review.db.models import ProposalReviewRule
from onyx.server.features.proposal_review.db.models import ProposalReviewRuleset
from onyx.server.features.proposal_review.db.models import ProposalReviewRun

# =============================================================================
# Ruleset Schemas
# =============================================================================


class RulesetCreate(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False


class RulesetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class RulesetResponse(BaseModel):
    id: UUID
    tenant_id: str
    name: str
    description: str | None
    is_default: bool
    is_active: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    rules: list["RuleResponse"] = []

    @classmethod
    def from_model(
        cls,
        ruleset: ProposalReviewRuleset,
        include_rules: bool = True,
    ) -> "RulesetResponse":
        return cls(
            id=ruleset.id,
            tenant_id=ruleset.tenant_id,
            name=ruleset.name,
            description=ruleset.description,
            is_default=ruleset.is_default,
            is_active=ruleset.is_active,
            created_by=ruleset.created_by,
            created_at=ruleset.created_at,
            updated_at=ruleset.updated_at,
            rules=(
                [RuleResponse.from_model(r) for r in ruleset.rules]
                if include_rules
                else []
            ),
        )


# =============================================================================
# Rule Schemas
# =============================================================================


class RuleCreate(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    rule_type: Literal[
        "DOCUMENT_CHECK", "METADATA_CHECK", "CROSS_REFERENCE", "CUSTOM_NL"
    ]
    rule_intent: Literal["CHECK", "HIGHLIGHT"] = "CHECK"
    prompt_template: str
    source: Literal["IMPORTED", "MANUAL"] = "MANUAL"
    authority: Literal["OVERRIDE", "RETURN"] | None = None
    is_hard_stop: bool = False
    priority: int = 0


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    rule_type: str | None = None
    rule_intent: str | None = None
    prompt_template: str | None = None
    authority: str | None = None
    is_hard_stop: bool | None = None
    priority: int | None = None
    is_active: bool | None = None
    refinement_needed: bool | None = None
    refinement_question: str | None = None


class RuleRefinementRequest(BaseModel):
    answer: str


class RuleResponse(BaseModel):
    id: UUID
    ruleset_id: UUID
    name: str
    description: str | None
    category: str | None
    rule_type: str
    rule_intent: str
    prompt_template: str
    source: str
    authority: str | None
    is_hard_stop: bool
    priority: int
    is_active: bool
    refinement_needed: bool
    refinement_question: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, rule: ProposalReviewRule) -> "RuleResponse":
        return cls(
            id=rule.id,
            ruleset_id=rule.ruleset_id,
            name=rule.name,
            description=rule.description,
            category=rule.category,
            rule_type=rule.rule_type,
            rule_intent=rule.rule_intent,
            prompt_template=rule.prompt_template,
            source=rule.source,
            authority=rule.authority,
            is_hard_stop=rule.is_hard_stop,
            priority=rule.priority,
            is_active=rule.is_active,
            refinement_needed=rule.refinement_needed,
            refinement_question=rule.refinement_question,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class BulkRuleUpdateRequest(BaseModel):
    """Batch activate/deactivate/delete rules."""

    action: Literal["activate", "deactivate", "delete"]
    rule_ids: list[UUID]


class BulkRuleUpdateResponse(BaseModel):
    updated_count: int


class RuleTestResponse(BaseModel):
    rule_id: str
    success: bool
    error: str | None = None
    result: dict[str, Any] | None = None


# =============================================================================
# Proposal Schemas
# =============================================================================


class ProposalResponse(BaseModel):
    """Proposal response including inline decision fields."""

    id: UUID
    document_id: str
    tenant_id: str
    status: str
    # Inline decision fields
    decision_notes: str | None = None
    decision_officer_id: UUID | None = None
    decision_at: datetime | None = None
    jira_synced: bool = False
    jira_synced_at: datetime | None = None

    created_at: datetime
    updated_at: datetime
    # Resolved metadata from Document table via field_mapping
    metadata: dict[str, Any] = {}

    @classmethod
    def from_model(
        cls,
        proposal: ProposalReviewProposal,
        metadata: dict[str, Any] | None = None,
    ) -> "ProposalResponse":
        return cls(
            id=proposal.id,
            document_id=proposal.document_id,
            tenant_id=proposal.tenant_id,
            status=proposal.status,
            decision_notes=proposal.decision_notes,
            decision_officer_id=proposal.decision_officer_id,
            decision_at=proposal.decision_at,
            jira_synced=proposal.jira_synced,
            jira_synced_at=proposal.jira_synced_at,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            metadata=metadata or {},
        )


class ProposalListResponse(BaseModel):
    proposals: list[ProposalResponse]
    total_count: int
    config_missing: bool = False  # True when no config exists


# =============================================================================
# Review Run Schemas
# =============================================================================


class ReviewRunTriggerRequest(BaseModel):
    ruleset_id: UUID


class ReviewRunResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    ruleset_id: UUID
    triggered_by: UUID
    status: str
    total_rules: int
    completed_rules: int
    failed_rules: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, run: ProposalReviewRun) -> "ReviewRunResponse":
        return cls(
            id=run.id,
            proposal_id=run.proposal_id,
            ruleset_id=run.ruleset_id,
            triggered_by=run.triggered_by,
            status=run.status,
            total_rules=run.total_rules,
            completed_rules=run.completed_rules,
            failed_rules=run.failed_rules,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )


# =============================================================================
# Finding Schemas
# =============================================================================


class FindingResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    rule_id: UUID
    review_run_id: UUID
    verdict: str
    confidence: str | None
    evidence: str | None
    explanation: str | None
    suggested_action: str | None
    llm_model: str | None
    llm_tokens_used: int | None
    created_at: datetime
    # Nested rule info for display
    rule_name: str | None = None
    rule_category: str | None = None
    rule_is_hard_stop: bool | None = None
    # Inline decision fields
    decision_action: str | None = None
    decision_notes: str | None = None
    decided_at: datetime | None = None

    @classmethod
    def from_model(cls, finding: ProposalReviewFinding) -> "FindingResponse":
        rule_name = None
        rule_category = None
        rule_is_hard_stop = None
        if finding.rule is not None:
            rule_name = finding.rule.name
            rule_category = finding.rule.category
            rule_is_hard_stop = finding.rule.is_hard_stop

        return cls(
            id=finding.id,
            proposal_id=finding.proposal_id,
            rule_id=finding.rule_id,
            review_run_id=finding.review_run_id,
            verdict=finding.verdict,
            confidence=finding.confidence,
            evidence=finding.evidence,
            explanation=finding.explanation,
            suggested_action=finding.suggested_action,
            llm_model=finding.llm_model,
            llm_tokens_used=finding.llm_tokens_used,
            created_at=finding.created_at,
            rule_name=rule_name,
            rule_category=rule_category,
            rule_is_hard_stop=rule_is_hard_stop,
            decision_action=finding.decision_action,
            decision_notes=finding.decision_notes,
            decided_at=finding.decided_at,
        )


# =============================================================================
# Decision Schemas
# =============================================================================


class FindingDecisionCreate(BaseModel):
    action: Literal["VERIFIED", "ISSUE", "NOT_APPLICABLE", "OVERRIDDEN"]
    notes: str | None = None


class ProposalDecisionCreate(BaseModel):
    decision: Literal["APPROVED", "CHANGES_REQUESTED", "REJECTED"]
    notes: str | None = None


class ProposalDecisionResponse(BaseModel):
    """Response after recording a proposal-level decision."""

    proposal_id: UUID
    status: str
    decision_notes: str | None
    jira_synced: bool
    decision_at: datetime | None

    @classmethod
    def from_proposal(
        cls, proposal: ProposalReviewProposal
    ) -> "ProposalDecisionResponse":
        return cls(
            proposal_id=proposal.id,
            status=proposal.status,
            decision_notes=proposal.decision_notes,
            jira_synced=proposal.jira_synced,
            decision_at=proposal.decision_at,
        )


# =============================================================================
# Config Schemas
# =============================================================================


class ConfigUpdate(BaseModel):
    jira_connector_id: int | None = None
    jira_project_key: str | None = None
    field_mapping: list[str] | None = None  # List of visible metadata keys
    jira_writeback: dict[str, Any] | None = None
    jira_issue_types: list[str] | None = None
    # LLM configuration
    review_model: str | None = None  # model name for rule evaluation
    import_model: str | None = None  # model name for checklist import


class ConfigResponse(BaseModel):
    id: UUID
    tenant_id: str
    jira_connector_id: int | None
    jira_project_key: str | None
    field_mapping: list[str] | None
    jira_writeback: dict[str, Any] | None
    jira_issue_types: list[str] | None
    review_model: str | None
    import_model: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, config: ProposalReviewConfig) -> "ConfigResponse":
        return cls(
            id=config.id,
            tenant_id=config.tenant_id,
            jira_connector_id=config.jira_connector_id,
            jira_project_key=config.jira_project_key,
            field_mapping=config.field_mapping,
            jira_writeback=config.jira_writeback,
            jira_issue_types=config.jira_issue_types,
            review_model=config.review_model,
            import_model=config.import_model,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


# =============================================================================
# Import Schemas
# =============================================================================


class ImportResponse(BaseModel):
    rules_created: int
    rules: list[RuleResponse]


class ImportJobResponse(BaseModel):
    id: UUID
    status: str
    source_filename: str
    rules_created: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_model(cls, job: ProposalReviewImportJob) -> "ImportJobResponse":
        return cls(
            id=job.id,
            status=job.status,
            source_filename=job.source_filename,
            rules_created=job.rules_created,
            error_message=job.error_message,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )


# =============================================================================
# Document Schemas
# =============================================================================


class ProposalDocumentResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    file_name: str
    file_type: str | None
    document_role: str
    uploaded_by: UUID | None
    extracted_text: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, doc: ProposalReviewDocument) -> "ProposalDocumentResponse":
        return cls(
            id=doc.id,
            proposal_id=doc.proposal_id,
            file_name=doc.file_name,
            file_type=doc.file_type,
            document_role=doc.document_role,
            uploaded_by=doc.uploaded_by,
            extracted_text=getattr(doc, "extracted_text", None),
            created_at=doc.created_at,
        )


# =============================================================================
# Jira Sync Schemas
# =============================================================================


class JiraSyncResponse(BaseModel):
    success: bool
    message: str


# =============================================================================
# Jira Connector Discovery Schemas
# =============================================================================


class JiraConnectorInfo(BaseModel):
    id: int
    name: str
    project_key: str
    project_url: str
