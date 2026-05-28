export const actionLabels: Record<string, string> = {
  "slack.send_message": "Craft is trying to send a message in Slack",
};

export function resolveActionLabel(actionType: string): string {
  return actionLabels[actionType] ?? actionType;
}
