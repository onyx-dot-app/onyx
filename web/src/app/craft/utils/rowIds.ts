/** DOM id of a message's row, the scroll view's anchor for a user message. */
export function craftMessageRowId(messageId: string): string {
  return `craft-message-${messageId}`;
}
