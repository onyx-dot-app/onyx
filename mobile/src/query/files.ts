// Recently-uploaded files for the attach popover (web's FilePickerPopover "Recent
// Files"). The upload itself is driven imperatively by useComposerAttachments.
import type { ProjectFile } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function useRecentFiles() {
  return useSimpleQuery<ProjectFile[]>(queryKeys.recentFiles);
}
