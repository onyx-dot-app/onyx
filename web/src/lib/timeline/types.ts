/** Where an entry is in its life. */
export type TimelineEntryStatus = "streaming" | "done" | "error" | "stopped";

/**
 * One item of a timeline: a reasoning block, a tool call, or another step.
 * Each product's adapter builds entries from its own stream; the timeline
 * code never reads the payload.
 */
export interface TimelineEntry<P> {
  /** Stable key; a later update with the same id replaces the entry. */
  id: string;
  status: TimelineEntryStatus;
  /** Entries with the same group id render together, e.g. parallel tool tabs. */
  groupId: string | null;
  payload: P;
}

export interface TimelineGroup<P> {
  /** The shared group id, or the entry id for an ungrouped entry. */
  id: string;
  entries: TimelineEntry<P>[];
  /** True when the group has more than one entry. */
  isParallel: boolean;
}

/** Where a step sits in the rail; the first and last steps draw no outer connector. */
export interface TimelineStepPosition {
  isFirst: boolean;
  isLast: boolean;
}
