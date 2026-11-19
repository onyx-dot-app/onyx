/**
 * Where each chat was scrolled, kept in memory for the page's lifetime, so a
 * chat opened again returns to where it was left. A reload forgets it.
 */

/** At the end, or a row's top relative to the viewport's top. */
export type SavedChatPosition =
  | { kind: "end" }
  | { kind: "row"; rowId: string; rowOffset: number };

export interface ChatScrollMemory {
  position: SavedChatPosition | null;
  /** Last measured height of each row, by row id, so a chat opened again
   *  lays out its windowed rows at their real heights. */
  rowHeights: Map<string, number>;
}

const memories = new Map<string, ChatScrollMemory>();

export function getChatScrollMemory(sessionId: string): ChatScrollMemory {
  const existing = memories.get(sessionId);
  if (existing) return existing;
  const memory: ChatScrollMemory = {
    position: null,
    rowHeights: new Map(),
  };
  memories.set(sessionId, memory);
  return memory;
}
