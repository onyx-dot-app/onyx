import type {
  TimelineEntry,
  TimelineEntryStatus,
  TimelineGroup,
} from "@/lib/timeline/types";

/** Replaces the entry with the same id in place, or appends a new entry. */
export function upsertTimelineEntry<P>(
  entries: readonly TimelineEntry<P>[],
  entry: TimelineEntry<P>
): TimelineEntry<P>[] {
  const index = entries.findIndex((existing) => existing.id === entry.id);
  if (index === -1) {
    return [...entries, entry];
  }
  return entries.map((existing, i) => (i === index ? entry : existing));
}

/** Sets the status of one entry. An unknown id leaves the list unchanged. */
export function setTimelineEntryStatus<P>(
  entries: readonly TimelineEntry<P>[],
  id: string,
  status: TimelineEntryStatus
): TimelineEntry<P>[] {
  return entries.map((entry) =>
    entry.id === id && entry.status !== status ? { ...entry, status } : entry
  );
}

/**
 * Groups entries by group id. Groups keep the order of their first entry, and
 * entries keep their order inside a group. An entry with no group id is a
 * group of its own.
 */
export function groupTimelineEntries<P>(
  entries: readonly TimelineEntry<P>[]
): TimelineGroup<P>[] {
  const groups = new Map<string, TimelineEntry<P>[]>();
  for (const entry of entries) {
    const key = entry.groupId ?? entry.id;
    const group = groups.get(key);
    if (group) {
      group.push(entry);
    } else {
      groups.set(key, [entry]);
    }
  }
  return Array.from(groups, ([id, groupEntries]) => ({
    id,
    entries: groupEntries,
    isParallel: groupEntries.length > 1,
  }));
}
