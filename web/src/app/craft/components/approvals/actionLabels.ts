// Human-readable labels for the per-endpoint action_ids emitted by the
// backend matcher. Keys mirror the `id` values defined on each catalog
// endpoint under `backend/onyx/external_apps/providers/<app>.py`.
//
// Unrecognized keys fall through to the raw action_id string — preferable
// to "SLACK" or similar all-caps app-type fallback, since the action_id
// is at least specific (e.g. "slack.messages.write").
export const actionLabels: Record<string, string> = {
  // Slack
  "slack.messages.write": "Craft wants to send a message in Slack",
  "slack.messages.read": "Craft wants to read messages in Slack",
  "slack.channels.read": "Craft wants to list Slack channels",
  "slack.users.read": "Craft wants to read Slack user info",
  "slack.search.read": "Craft wants to search Slack",

  // Linear
  "linear.viewer.read": "Craft wants to read your Linear account",
  "linear.teams.read": "Craft wants to list Linear teams",
  "linear.issues.read": "Craft wants to read Linear issues",
  "linear.projects.read": "Craft wants to read Linear projects",
  "linear.issues.create": "Craft wants to create a Linear issue",
  "linear.comments.create": "Craft wants to comment on a Linear issue",

  // Google Calendar
  "gcal.calendars.read": "Craft wants to list your calendars",
  "gcal.events.read": "Craft wants to read calendar events",
  "gcal.freebusy.read": "Craft wants to check your free/busy schedule",
  "gcal.events.create": "Craft wants to create a calendar event",
  "gcal.events.update": "Craft wants to update a calendar event",
  "gcal.events.delete": "Craft wants to delete a calendar event",
};

export function resolveActionLabel(actionType: string): string {
  return actionLabels[actionType] ?? actionType;
}
