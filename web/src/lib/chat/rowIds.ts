import type { Message } from "@/app/app/types";

// Database message id → the temporary node id its row was first shown with.
const firstShownNodeIds = new Map<number, number>();

/**
 * DOM id of a message's row. A sent turn has temporary node ids until a
 * refetch replaces them with database ids. The row keeps the id it was first
 * shown with, so a refetch neither remounts it nor reads as a new turn.
 */
export function messageRowId(message: Message): string {
  const { messageId, nodeId } = message;
  if (messageId === undefined) return `message-${nodeId}`;
  const firstShown = firstShownNodeIds.get(messageId);
  if (firstShown !== undefined) return `message-${firstShown}`;
  if (nodeId !== messageId) firstShownNodeIds.set(messageId, nodeId);
  return `message-${nodeId}`;
}

/** Database message id of a row, or null for a turn shown with temporary
 *  node ids (it is never on an older page). */
export function messageIdFromRowId(rowId: string): number | null {
  const id = Number(rowId.replace(/^message-/, ""));
  return Number.isInteger(id) && id > 0 ? id : null;
}
