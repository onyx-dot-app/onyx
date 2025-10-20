import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSetSummary, MinimalUserSnapshot } from "@/lib/types";

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
  llm_model_version_override?: string;
  llm_model_provider_override?: string;

  uploaded_image_id?: string;
  icon_shape?: number;
  icon_color?: string;

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

  // Embedded prompt fields on persona
  system_prompt: string | null;
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
