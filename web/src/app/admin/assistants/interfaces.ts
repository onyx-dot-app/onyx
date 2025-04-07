import { ToolSnapshot } from "@/lib/tools/interfaces";
import { DocumentSet, MinimalUserSnapshot } from "@/lib/types";

export interface StarterMessageBase {
  message: string;
}
export interface StarterMessage extends StarterMessageBase {
  name: string;
}

export interface Prompt {
  id: number;
  name: string;
  description: string;
  system_prompt: string;
  task_prompt: string;
  include_citations: boolean;
  datetime_aware: boolean;
  default_prompt: boolean;
}

export interface Persona {
  id: number;
  name: string;
  search_start_date: Date | null;
  owner: MinimalUserSnapshot | null;
  is_visible: boolean;
  is_public: boolean;
  display_priority: number | null;
  description: string;
  document_sets: DocumentSet[];
  prompts: Prompt[];
  tools: ToolSnapshot[];
  num_chunks?: number;
  llm_relevance_filter?: boolean;
  llm_filter_extraction?: boolean;
  llm_model_provider_override?: string;
  llm_model_version_override?: string;
  starter_messages: StarterMessage[] | null;
  builtin_persona: boolean;
  is_default_persona: boolean;
  users: MinimalUserSnapshot[];
  groups: number[];
  icon_shape?: number;
  icon_color?: string;
  uploaded_image_id?: string;
  labels?: PersonaLabel[];
}

export interface PersonaLabel {
  id: number;
  name: string;
}
