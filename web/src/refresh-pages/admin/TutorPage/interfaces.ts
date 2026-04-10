import type { MinimalUserSnapshot } from "@/lib/types";

export interface TutorRow {
  id: number;
  name: string;
  description: string;
  is_public: boolean;
  is_listed: boolean;
  owner: MinimalUserSnapshot | null;
  uploaded_image_id?: string;
  icon_name?: string;
  system_prompt: string | null;
}
