import type { TimelineEntry, TimelineGroup } from "@/lib/timeline/types";

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
