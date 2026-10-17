import type { ProjectFile } from "@/lib/projects/types";

/**
 * Remove viewer-staged uploads without touching files already in the chat.
 * Upload completion may replace an optimistic id with a server id while
 * retaining temp_id, so match both identifiers.
 */
export function filterOutStagedViewerFiles(
  files: ProjectFile[],
  stagedIds: ReadonlySet<string>
): ProjectFile[] {
  return files.filter(
    (file) =>
      !stagedIds.has(file.id) &&
      !(file.temp_id && stagedIds.has(file.temp_id))
  );
}
