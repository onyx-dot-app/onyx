import type { TimelineEntry, TimelineGroup } from "@/lib/timeline/types";

/**
 * Groups entries by group id. Groups keep the order of their first entry, and
 * entries keep their order inside a group. An entry with no group id is a
 * group of its own.
 */
export function groupTimelineEntries<P>(
  entries: readonly TimelineEntry<P>[]
): TimelineGroup<P>[] {
  // Group ids and entry ids are separate namespaces, so an ungrouped entry
  // never joins a group whose id equals its own.
  const groups = new Map<string, { id: string; entries: TimelineEntry<P>[] }>();
  for (const entry of entries) {
    const key =
      entry.groupId === null ? `entry:${entry.id}` : `group:${entry.groupId}`;
    const group = groups.get(key);
    if (group) {
      group.entries.push(entry);
    } else {
      groups.set(key, { id: entry.groupId ?? entry.id, entries: [entry] });
    }
  }
  return Array.from(groups.values(), ({ id, entries: groupEntries }) => ({
    id,
    entries: groupEntries,
    isParallel: groupEntries.length > 1,
  }));
}
