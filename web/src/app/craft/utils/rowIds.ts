/** DOM id of a user message's row, the scroll container's anchor. */
export function craftMessageRowId(messageId: string): string {
  return `craft-message-${messageId}`;
}
