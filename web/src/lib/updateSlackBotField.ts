import { SlackBot } from "@/lib/types";

export async function updateSlackBotField(
  slackBot: SlackBot,
  field: keyof SlackBot,
  value: any
): Promise<Response> {
  return fetch(`/api/manage/admin/slack-app/bots/${slackBot.id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...slackBot,
      [field]: value,
    }),
  });
}
