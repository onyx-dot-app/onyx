import { ValidSources } from "@/lib/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSetSummary, MinimalUserSnapshot } from "@/lib/types";

// ── Domain / application types ────────────────────────────────────────────────

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

export interface MinimalAgentSnapshot {
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

export interface Persona extends MinimalAgentSnapshot {
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
