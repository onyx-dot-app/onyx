// Chat-attachment file queries.
//
// - useRecentFiles: GET /user/files/recent — the user's recently-uploaded Onyx
//   files, surfaced in the attach popover for one-tap re-attach (web parity:
//   FilePickerPopover "Recent Files").
//
// The multipart upload itself is driven imperatively (per file, for per-tile
// status) by `useComposerAttachments`, which invalidates `recentFiles` on success.
import type { ProjectFile } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

/** The user's recently-uploaded files (bare `ProjectFile[]`, newest first). */
export function useRecentFiles() {
  return useSimpleQuery<ProjectFile[]>(queryKeys.recentFiles);
}
