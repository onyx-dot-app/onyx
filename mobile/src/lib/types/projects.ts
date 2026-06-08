// Mirrors web projectsService.ts.

import type { ChatSession } from "./chat";
import type { ProjectFile } from "./files";

export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  user_id: string;
  instructions: string | null;
  chat_sessions: ChatSession[];
}

export interface ProjectDetails {
  project: Project;
  files?: ProjectFile[];
  persona_id_to_is_featured?: Record<number, boolean>;
}
