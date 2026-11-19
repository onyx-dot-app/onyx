/**
 * Per-view scroll memory, kept for the page's lifetime. A view opened again
 * returns to where it was left. A reload forgets it.
 */

/** A row and its top, relative to the viewport's top. Rows are windowed, so a
 *  position is a row, not a scrollTop. */
export interface HeldRow {
  rowId: string;
  /** Finds the row when its id changed (a refetch can re-id a turn). */
  rowIndexFromEnd: number;
  rowOffset: number;
}

export type SavedScrollPosition = { kind: "end" } | ({ kind: "row" } & HeldRow);

export interface ScrollMemory {
  position: SavedScrollPosition | null;
  /** The turn whose anchor has space below it. */
  spaceTurnKey: string | null;
  /** Last measured height of each row, by row id. */
  rowHeights: Map<string, number>;
}

export function createScrollMemory(): ScrollMemory {
  return { position: null, spaceTurnKey: null, rowHeights: new Map() };
}

const memories = new Map<string, ScrollMemory>();

export function getScrollMemory(viewKey: string): ScrollMemory {
  const existing = memories.get(viewKey);
  if (existing) return existing;
  const memory = createScrollMemory();
  memories.set(viewKey, memory);
  return memory;
}
