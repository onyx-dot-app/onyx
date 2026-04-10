"""Pydantic request/response models for Proposal Review (Argus)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
        ruleset: Any,
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
    rule_type: str  # DOCUMENT_CHECK | METADATA_CHECK | CROSS_REFERENCE | CUSTOM_NL
    rule_intent: str = "CHECK"  # CHECK | HIGHLIGHT
    prompt_template: str
    source: str = "MANUAL"  # IMPORTED | MANUAL
    authority: str | None = None  # OVERRIDE | RETURN
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
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, rule: Any) -> "RuleResponse":
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
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class BulkRuleUpdateRequest(BaseModel):
    """Batch activate/deactivate/delete rules."""

    action: str  # "activate" | "deactivate" | "delete"
    rule_ids: list[UUID]


class BulkRuleUpdateResponse(BaseModel):
    updated_count: int


# =============================================================================
# Proposal Schemas
# =============================================================================


class ProposalResponse(BaseModel):
    """Thin response -- status + document_id. Metadata comes from Document."""

    id: UUID
    document_id: str
    tenant_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    # Resolved metadata from Document table via field_mapping
    metadata: dict[str, Any] = {}

    @classmethod
    def from_model(
        cls,
        proposal: Any,
        metadata: dict[str, Any] | None = None,
    ) -> "ProposalResponse":
        return cls(
            id=proposal.id,
            document_id=proposal.document_id,
            tenant_id=proposal.tenant_id,
            status=proposal.status,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            metadata=metadata or {},
        )


class ProposalListResponse(BaseModel):
    proposals: list[ProposalResponse]
    total_count: int
    config_missing: bool = False  # True when no Argus config exists


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
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, run: Any) -> "ReviewRunResponse":
        return cls(
            id=run.id,
            proposal_id=run.proposal_id,
            ruleset_id=run.ruleset_id,
            triggered_by=run.triggered_by,
            status=run.status,
            total_rules=run.total_rules,
            completed_rules=run.completed_rules,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )


# =============================================================================
# Finding Schemas
# =============================================================================


class FindingDecisionResponse(BaseModel):
    id: UUID
    finding_id: UUID
    officer_id: UUID
    action: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, decision: Any) -> "FindingDecisionResponse":
        return cls(
            id=decision.id,
            finding_id=decision.finding_id,
            officer_id=decision.officer_id,
            action=decision.action,
            notes=decision.notes,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
        )


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
    # Nested decision if exists
    decision: FindingDecisionResponse | None = None

    @classmethod
    def from_model(cls, finding: Any) -> "FindingResponse":
        decision = None
        if finding.decision is not None:
            decision = FindingDecisionResponse.from_model(finding.decision)

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
            decision=decision,
        )


# =============================================================================
# Decision Schemas
# =============================================================================


class FindingDecisionCreate(BaseModel):
    action: str  # VERIFIED | ISSUE | NOT_APPLICABLE | OVERRIDDEN
    notes: str | None = None


class ProposalDecisionCreate(BaseModel):
    decision: str  # APPROVED | CHANGES_REQUESTED | REJECTED
    notes: str | None = None


class ProposalDecisionResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    officer_id: UUID
    decision: str
    notes: str | None
    jira_synced: bool
    jira_synced_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, decision: Any) -> "ProposalDecisionResponse":
        return cls(
            id=decision.id,
            proposal_id=decision.proposal_id,
            officer_id=decision.officer_id,
            decision=decision.decision,
            notes=decision.notes,
            jira_synced=decision.jira_synced,
            jira_synced_at=decision.jira_synced_at,
            created_at=decision.created_at,
        )


# =============================================================================
# Config Schemas
# =============================================================================


class ConfigUpdate(BaseModel):
    jira_connector_id: int | None = None
    jira_project_key: str | None = None
    field_mapping: dict[str, Any] | None = None
    jira_writeback: dict[str, Any] | None = None


class ConfigResponse(BaseModel):
    id: UUID
    tenant_id: str
    jira_connector_id: int | None
    jira_project_key: str | None
    field_mapping: dict[str, Any] | None
    jira_writeback: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, config: Any) -> "ConfigResponse":
        return cls(
            id=config.id,
            tenant_id=config.tenant_id,
            jira_connector_id=config.jira_connector_id,
            jira_project_key=config.jira_project_key,
            field_mapping=config.field_mapping,
            jira_writeback=config.jira_writeback,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


# =============================================================================
# Import Schemas
# =============================================================================


class ImportResponse(BaseModel):
    rules_created: int
    rules: list[RuleResponse]


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
    def from_model(cls, doc: Any) -> "ProposalDocumentResponse":
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
# Audit Log Schemas
# =============================================================================


class AuditLogEntry(BaseModel):
    id: UUID
    proposal_id: UUID
    user_id: UUID | None
    action: str
    details: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_model(cls, entry: Any) -> "AuditLogEntry":
        return cls(
            id=entry.id,
            proposal_id=entry.proposal_id,
            user_id=entry.user_id,
            action=entry.action,
            details=entry.details,
            created_at=entry.created_at,
        )


# =============================================================================
# Jira Sync Schemas
# =============================================================================


class JiraSyncResponse(BaseModel):
    success: bool
    message: str
