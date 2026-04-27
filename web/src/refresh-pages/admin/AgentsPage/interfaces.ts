import type { MinimalUserSnapshot } from "@/lib/types";
import type { ToolSnapshot } from "@/lib/tools/interfaces";

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
