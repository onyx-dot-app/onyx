import { fetchDirectoryListing } from "@/app/craft/services/apiServices";
import type { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import type { SearchInventory } from "@/lib/build/types";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";

/** Lists directories in bounded batches without fetching file contents. */
export async function loadSearchInventory(
  sessionId: string,
  signal: AbortSignal
): Promise<SearchInventory> {
  const pending = [""];
  const seen = new Set<string>();
  const entries = new Map<string, FileSystemEntry>();
  const failedDirectories: string[] = [];
  while (pending.length && !signal.aborted) {
    const batch = pending.splice(0, 4).filter((path) => !seen.has(path));
    batch.forEach((path) => seen.add(path));
    const results = await Promise.allSettled(
      batch.map((path) => fetchDirectoryListing(sessionId, path, signal))
    );
    for (const [index, result] of results.entries()) {
      if (result.status === "rejected") {
        const path = batch[index];
        if (signal.aborted || isAuthStatusError(result.reason) || !path)
          throw result.reason;
        if (isNotFoundError(result.reason)) continue;
        failedDirectories.push(path);
        continue;
      }
      for (const entry of result.value.entries) {
        if (entry.is_directory) {
          if (!seen.has(entry.path)) pending.push(entry.path);
        } else entries.set(entry.path, entry);
      }
    }
  }
  signal.throwIfAborted();
  return {
    entries: [...entries.values()],
    complete: failedDirectories.length === 0,
    failedDirectories,
  };
}
