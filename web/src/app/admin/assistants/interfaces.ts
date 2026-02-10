import { ValidSources } from "@/lib/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSetSummary, MinimalUserSnapshot } from "@/lib/types";

// Represents a hierarchy node (folder, space, channel, etc.) attached to a persona
export interface HierarchyNodeSnapshot {
  id: number;
  raw_node_id: string;
  display_name: string;
  link: string | null;
  source: ValidSources;
  node_type: string; // HierarchyNodeType enum value
}

// Represents a document attached to a persona
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

export interface MinimalPersonaSnapshot {
  id: number;
  name: string;
  description: string;
  tools: ToolSnapshot[];
  starter_messages: StarterMessage[] | null;
  document_sets: DocumentSetSummary[];
  // Counts for knowledge sources (used to determine if search tool should be enabled)
  hierarchy_node_count?: number;
  attached_document_count?: number;
  // Unique sources from all knowledge (document sets + hierarchy nodes)
  // Used to populate source filters in chat
  knowledge_sources?: ValidSources[];
  llm_model_version_override?: string;
  llm_model_provider_override?: string;

  uploaded_image_id?: string;
  icon_name?: string;

  is_public: boolean;
  is_visible: boolean;
  display_priority: number | null;
  is_default_persona: boolean;
  builtin_persona: boolean;

  labels?: PersonaLabel[];
  owner: MinimalUserSnapshot | null;
}

export interface Persona extends MinimalPersonaSnapshot {
  user_file_ids: string[];
  users: MinimalUserSnapshot[];
  groups: number[];
  num_chunks?: number;
  // Hierarchy nodes (folders, spaces, channels) attached for scoped search
  hierarchy_nodes?: HierarchyNodeSnapshot[];
  // Individual documents attached for scoped search
  attached_documents?: AttachedDocumentSnapshot[];

  // Embedded prompt fields on persona
  system_prompt: string | null;
  replace_base_system_prompt: boolean;
  task_prompt: string | null;
  datetime_aware: boolean;
}

export interface FullPersona extends Persona {
  search_start_date: Date | null;
  llm_relevance_filter?: boolean;
  llm_filter_extraction?: boolean;
}

export interface PersonaLabel {
  id: number;
  name: string;
}
