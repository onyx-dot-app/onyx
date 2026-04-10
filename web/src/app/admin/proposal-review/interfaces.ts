/** Shared types for Proposal Review (Argus) admin pages. */

export interface RulesetResponse {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  rules: RuleResponse[];
}

export interface RuleResponse {
  id: string;
  ruleset_id: string;
  name: string;
  description: string | null;
  category: string | null;
  rule_type: RuleType;
  rule_intent: RuleIntent;
  prompt_template: string;
  source: RuleSource;
  authority: RuleAuthority | null;
  is_hard_stop: boolean;
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type RuleType =
  | "DOCUMENT_CHECK"
  | "METADATA_CHECK"
  | "CROSS_REFERENCE"
  | "CUSTOM_NL";

export type RuleIntent = "CHECK" | "HIGHLIGHT";

export type RuleSource = "IMPORTED" | "MANUAL";

export type RuleAuthority = "OVERRIDE" | "RETURN";

export interface RulesetCreate {
  name: string;
  description?: string;
  is_default?: boolean;
}

export interface RulesetUpdate {
  name?: string;
  description?: string;
  is_default?: boolean;
  is_active?: boolean;
}

export interface RuleCreate {
  name: string;
  description?: string;
  category?: string;
  rule_type: RuleType;
  rule_intent?: RuleIntent;
  prompt_template: string;
  source?: RuleSource;
  authority?: RuleAuthority | null;
  is_hard_stop?: boolean;
  priority?: number;
}

export interface RuleUpdate {
  name?: string;
  description?: string;
  category?: string;
  rule_type?: RuleType;
  rule_intent?: RuleIntent;
  prompt_template?: string;
  authority?: RuleAuthority | null;
  is_hard_stop?: boolean;
  priority?: number;
  is_active?: boolean;
}

export interface BulkRuleUpdateRequest {
  action: "activate" | "deactivate" | "delete";
  rule_ids: string[];
}

export interface BulkRuleUpdateResponse {
  updated_count: number;
}

export interface ImportResponse {
  rules_created: number;
  rules: RuleResponse[];
}

export interface ConfigResponse {
  id: string;
  tenant_id: string;
  jira_connector_id: number | null;
  jira_project_key: string | null;
  field_mapping: Record<string, string> | null;
  jira_writeback: Record<string, string> | null;
  created_at: string;
  updated_at: string;
}

export interface ConfigUpdate {
  jira_connector_id?: number | null;
  jira_project_key?: string | null;
  field_mapping?: Record<string, string> | null;
  jira_writeback?: Record<string, string> | null;
}

/** Labels for display purposes. */
export const RULE_TYPE_LABELS: Record<RuleType, string> = {
  DOCUMENT_CHECK: "Document Check",
  METADATA_CHECK: "Metadata Check",
  CROSS_REFERENCE: "Cross Reference",
  CUSTOM_NL: "Custom NL",
};

export const RULE_INTENT_LABELS: Record<RuleIntent, string> = {
  CHECK: "Check",
  HIGHLIGHT: "Highlight",
};

export const RULE_SOURCE_LABELS: Record<RuleSource, string> = {
  IMPORTED: "Imported",
  MANUAL: "Manual",
};

export const RULE_AUTHORITY_LABELS: Record<string, string> = {
  OVERRIDE: "Override",
  RETURN: "Return",
};
