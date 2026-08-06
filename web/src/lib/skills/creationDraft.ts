import type { PreparedSkillFilesUpload } from "@/lib/skills/bundleUpload";
import type { SkillBundleContents } from "@/lib/skills/types";

export interface SkillCreationDraft {
  contents: SkillBundleContents;
  upload: PreparedSkillFilesUpload;
}

interface PendingSkillCreationDraft {
  id: string;
  draft: SkillCreationDraft;
}

let pendingDraft: PendingSkillCreationDraft | undefined;

export function stageSkillCreationDraft(draft: SkillCreationDraft): string {
  const id = crypto.randomUUID();
  pendingDraft = { id, draft };
  return id;
}

export function getSkillCreationDraft(
  id: string
): SkillCreationDraft | undefined {
  return pendingDraft?.id === id ? pendingDraft.draft : undefined;
}

export function discardSkillCreationDraft(id: string): void {
  if (pendingDraft?.id === id) pendingDraft = undefined;
}
