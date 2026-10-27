import { fetchDirectoryListing } from "@/app/craft/services/apiServices";
import type { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import type { SearchInventory } from "@/lib/build/types";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";

export const MAX_SEARCH_ENTRIES = 10_000;
const MAX_DIRECTORIES = 128;
const SEARCH_BUDGET_MS = 10_000;

/** Bounds total work; an in-flight batch also has the directory API's timeout. */
export async function loadSearchInventory(
  sessionId: string,
  signal: AbortSignal
): Promise<SearchInventory> {
  const pending = [""];
  const seen = new Set<string>();
  const entries = new Map<string, FileSystemEntry>();
  const failedDirectories: string[] = [];
  const deadline = Date.now() + SEARCH_BUDGET_MS;
  let examined = 0;
  while (pending.length && !signal.aborted) {
    if (
      seen.size >= MAX_DIRECTORIES ||
      examined >= MAX_SEARCH_ENTRIES ||
      Date.now() >= deadline
    )
      break;
    const batch = pending
      .splice(0, Math.min(4, MAX_DIRECTORIES - seen.size))
      .filter((path) => !seen.has(path));
    batch.forEach((path) => seen.add(path));
    const results = await Promise.allSettled(
      batch.map((path) => fetchDirectoryListing(sessionId, path, signal))
    );
    for (const [index, result] of results.entries()) {
      const path = batch[index] ?? "";
      if (result.status === "rejected") {
        if (signal.aborted || isAuthStatusError(result.reason) || !path)
          throw result.reason;
        if (isNotFoundError(result.reason)) continue;
        failedDirectories.push(path);
        continue;
      }
      for (const entry of result.value.entries) {
        if (examined >= MAX_SEARCH_ENTRIES) {
          failedDirectories.push(path);
          break;
        }
        examined++;
        if (entry.is_directory) {
          if (!seen.has(entry.path)) pending.push(entry.path);
        } else entries.set(entry.path, entry);
      }
    }
  }
  signal.throwIfAborted();
  failedDirectories.push(...pending);
  return {
    entries: [...entries.values()],
    complete: failedDirectories.length === 0,
    failedDirectories,
  };
}
