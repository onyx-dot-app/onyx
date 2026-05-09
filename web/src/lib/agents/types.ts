import { ValidSources } from "@/lib/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSetSummary, MinimalUserSnapshot } from "@/lib/types";

export interface HierarchyNodeSnapshot {
  id: number;
  raw_node_id: string;
  display_name: string;
  link: string | null;
  source: ValidSources;
  node_type: string;
}

export interface AttachedDocumentSnapshot {
  id: string;
  title: string;
  link: string | null;
  parent_id: number | null;
  last_modified: string | null;
  last_synced: string | null;
  source: ValidSources | null;
}

export interface StarterMessageBase {
  message: string;
}

export interface StarterMessage extends StarterMessageBase {
  name: string;
}

export interface PersonaLabel {
  id: number;
  name: string;
}

export interface MinimalPersonaSnapshot {
  id: number;
  name: string;
  description: string;
  tools: ToolSnapshot[];
  starter_messages: StarterMessage[] | null;
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
  labels?: PersonaLabel[];
  owner: MinimalUserSnapshot | null;
}

export interface Persona extends MinimalPersonaSnapshot {
  user_file_ids: string[];
  users: MinimalUserSnapshot[];
  groups: number[];
  hierarchy_nodes?: HierarchyNodeSnapshot[];
  attached_documents?: AttachedDocumentSnapshot[];
  system_prompt: string | null;
  replace_base_system_prompt: boolean;
  task_prompt: string | null;
  datetime_aware: boolean;
}

export interface FullPersona extends Persona {
  search_start_date: string | null;
}

export interface PersonaUpsertParameters {
  name: string;
  description: string;
  system_prompt: string;
  replace_base_system_prompt: boolean;
  task_prompt: string;
  datetime_aware: boolean;
  document_set_ids: number[];
  is_public: boolean;
  default_model_configuration_id?: number | null;
  starter_messages: StarterMessage[] | null;
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

export interface AgentRow {
  id: number;
  name: string;
  description: string;
  is_public: boolean;
  is_listed: boolean;
  is_featured: boolean;
  builtin_persona: boolean;
  display_priority: number | null;
  owner: MinimalUserSnapshot | null;
  groups: number[];
  users: MinimalUserSnapshot[];
  tools: ToolSnapshot[];
  uploaded_image_id?: string;
  icon_name?: string;
}

export type FetchAgentsResponse = [MinimalPersonaSnapshot[], string | null];
