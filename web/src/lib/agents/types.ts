import { ValidSources } from "@/lib/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSetSummary, MinimalUserSnapshot } from "@/lib/types";

// ── Domain / application types ────────────────────────────────────────────────

export interface AgentHierarchyNode {
  id: number;
  raw_node_id: string;
  display_name: string;
  link: string | null;
  source: ValidSources;
  node_type: string;
}

export interface AgentAttachedDocument {
  id: string;
  title: string;
  link: string | null;
  parent_id: number | null;
  last_modified: string | null;
  last_synced: string | null;
  source: ValidSources | null;
}

export interface AgentStarterMessage {
  name: string;
  message: string;
}

export interface AgentLabel {
  id: number;
  name: string;
}

export interface MinimalAgent {
  id: number;
  name: string;
  description: string;
  tools: ToolSnapshot[];
  starter_messages: AgentStarterMessage[] | null;
  document_sets: DocumentSetSummary[];
  hierarchy_node_count?: number;
  attached_document_count?: number;
  knowledge_sources?: ValidSources[];
  default_model_configuration_id?: number | null;
  uploaded_image_id?: string;
  icon_name?: string;
  is_public: boolean;
  is_listed: boolean;
  display_priority: number | null;
  is_featured: boolean;
  builtin_persona: boolean;
  labels?: AgentLabel[];
  owner: MinimalUserSnapshot | null;
}

export interface Agent extends MinimalAgent {
  user_file_ids: string[];
  users: MinimalUserSnapshot[];
  groups: number[];
  hierarchy_nodes?: AgentHierarchyNode[];
  attached_documents?: AgentAttachedDocument[];
  system_prompt: string | null;
  replace_base_system_prompt: boolean;
  task_prompt: string | null;
  datetime_aware: boolean;
}

export interface FullAgent extends Agent {
  search_start_date: string | null;
}

// ── Upsert / API parameter types ──────────────────────────────────────────────

export interface AgentUpsertParameters {
  name: string;
  description: string;
  system_prompt: string;
  replace_base_system_prompt: boolean;
  task_prompt: string;
  datetime_aware: boolean;
  document_set_ids: number[];
  is_public: boolean;
  default_model_configuration_id?: number | null;
  starter_messages: AgentStarterMessage[] | null;
  users?: string[];
  groups: number[];
  tool_ids: number[];
  remove_image?: boolean;
  search_start_date: Date | null;
  uploaded_image_id: string | null;
  icon_name: string | null;
  is_featured: boolean;
  label_ids: number[] | null;
  user_file_ids: string[];
  hierarchy_node_ids?: number[];
  document_ids?: string[];
}

export interface AgentUpsertRequest {
  name: string;
  description: string;
  system_prompt: string;
  task_prompt: string;
  datetime_aware: boolean;
  document_set_ids: number[];
  is_public: boolean;
  default_model_configuration_id: number | null;
  starter_messages: AgentStarterMessage[] | null;
  users?: string[];
  groups: number[];
  tool_ids: number[];
  remove_image?: boolean;
  uploaded_image_id: string | null;
  icon_name: string | null;
  search_start_date: Date | null;
  is_featured: boolean;
  display_priority: number | null;
  label_ids: number[] | null;
  user_file_ids: string[] | null;
  replace_base_system_prompt: boolean;
  hierarchy_node_ids: number[];
  document_ids: string[];
}

export interface PaginatedAgentsResponse {
  items: Agent[];
  total_items: number;
}
