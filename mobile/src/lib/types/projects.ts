// Mirrors web projectsService.ts (the `Project` / `ProjectDetails` shapes the
// mobile UI needs). `ProjectFile`, `CategorizedFiles`, `RejectedFile`, and
// `UserFileStatus` live in ./files.

import type { ChatSession } from "./chat";
import type { ProjectFile } from "./files";

/**
 * A user project. Returned by `GET /user/projects` (with `chat_sessions`
 * populated for the sidebar folder list) and `GET /user/projects/{id}`.
 */
export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  user_id: string;
  instructions: string | null;
  chat_sessions: ChatSession[];
}

/**
 * Full per-project payload from `GET /user/projects/{id}/details`: the project,
 * its linked files, and a map of which personas are "featured" (used by web to
 * decide avatar vs glyph — mobile renders a glyph for all).
 */
export interface ProjectDetails {
  project: Project;
  files?: ProjectFile[];
  persona_id_to_is_featured?: Record<number, boolean>;
}
