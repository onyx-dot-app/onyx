// ---------------------------------------------------------------------------
// Proposal Review Types
//
// TypeScript interfaces matching backend response schemas for the
// proposal-review feature (Argus).
// ---------------------------------------------------------------------------

// --- Enums / Literal Unions ---

export type ProposalStatus =
  | "PENDING"
  | "IN_REVIEW"
  | "APPROVED"
  | "CHANGES_REQUESTED"
  | "REJECTED";

export type ReviewRunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type FindingVerdict =
  | "PASS"
  | "FAIL"
  | "FLAG"
  | "NEEDS_REVIEW"
  | "NOT_APPLICABLE";

export type FindingConfidence = "HIGH" | "MEDIUM" | "LOW";

export type DecisionAction =
  | "VERIFIED"
  | "ISSUE"
  | "NOT_APPLICABLE"
  | "OVERRIDDEN";

export type ProposalDecisionOutcome =
  | "APPROVED"
  | "CHANGES_REQUESTED"
  | "REJECTED";

export type RuleType =
  | "DOCUMENT_CHECK"
  | "METADATA_CHECK"
  | "CROSS_REFERENCE"
  | "CUSTOM_NL";

export type RuleIntent = "CHECK" | "HIGHLIGHT";

export type RuleAuthority = "OVERRIDE" | "RETURN" | null;

export type DocumentRole =
  | "PROPOSAL"
  | "BUDGET"
  | "FOA"
  | "INTERNAL"
  | "SOW"
  | "OTHER";

export type AuditAction =
  | "review_triggered"
  | "finding_decided"
  | "decision_submitted"
  | "jira_synced"
  | "document_uploaded";

// --- Core Interfaces ---

export interface ProposalMetadata {
  jira_key?: string;
  title?: string;
  pi_name?: string;
  sponsor?: string;
  deadline?: string;
  agreement_type?: string;
  officer?: string;
  [key: string]: string | undefined;
}

export interface Proposal {
  id: string;
  document_id: string;
  tenant_id: string;
  status: ProposalStatus;
  metadata: ProposalMetadata;
  created_at: string;
  updated_at: string;
}

export interface Ruleset {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Rule {
  id: string;
  ruleset_id: string;
  name: string;
  description: string | null;
  category: string | null;
  rule_type: RuleType;
  rule_intent: RuleIntent;
  authority: RuleAuthority;
  is_hard_stop: boolean;
  priority: number;
  is_active: boolean;
}

export interface ReviewRun {
  id: string;
  proposal_id: string;
  ruleset_id: string;
  triggered_by: string;
  status: ReviewRunStatus;
  total_rules: number;
  completed_rules: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ReviewStatus {
  status: ReviewRunStatus;
  total_rules: number;
  completed_rules: number;
}

export interface FindingDecision {
  id: string;
  finding_id: string;
  officer_id: string;
  action: DecisionAction;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  id: string;
  proposal_id: string;
  rule_id: string;
  review_run_id: string;
  verdict: FindingVerdict;
  confidence: FindingConfidence | null;
  evidence: string | null;
  explanation: string | null;
  suggested_action: string | null;
  llm_model: string | null;
  llm_tokens_used: number | null;
  created_at: string;
  // Flattened rule info from the backend FindingResponse
  rule_name: string | null;
  rule_category: string | null;
  rule_is_hard_stop: boolean | null;
  decision: FindingDecision | null;
}

export interface ProposalDocument {
  id: string;
  proposal_id: string;
  file_name: string;
  file_type: string | null;
  document_role: DocumentRole;
  uploaded_by: string | null;
  extracted_text: string | null;
  created_at: string;
}

export interface ProposalDecision {
  id: string;
  proposal_id: string;
  officer_id: string;
  decision: ProposalDecisionOutcome;
  notes: string | null;
  jira_synced: boolean;
  jira_synced_at: string | null;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  proposal_id: string;
  user_id: string | null;
  action: AuditAction;
  details: Record<string, unknown> | null;
  created_at: string;
}

// --- Grouped findings by category ---

export interface FindingsByCategory {
  category: string;
  findings: Finding[];
}
