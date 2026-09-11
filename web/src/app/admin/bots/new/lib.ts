export interface SlackBotCreationRequest {
  name: string;
  enabled: boolean;

  bot_token: string;
  app_token: string;
  user_token?: string;
}

const buildRequestBodyFromCreationRequest = (
  creationRequest: SlackBotCreationRequest
): string => {
  return JSON.stringify({
    name: creationRequest.name,
    enabled: creationRequest.enabled,
    bot_token: creationRequest.bot_token,
    app_token: creationRequest.app_token,
    user_token: creationRequest.user_token,
  });
};

export const createSlackBot = async (
  creationRequest: SlackBotCreationRequest
) => {
  return fetch("/api/manage/admin/slack-app/bots", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const updateSlackBot = async (
  id: number,
  creationRequest: SlackBotCreationRequest
) => {
  return fetch(`/api/manage/admin/slack-app/bots/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const deleteSlackBot = async (id: number) => {
  return fetch(`/api/manage/admin/slack-app/bots/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

/**
 * Reads the error message from a failed Slack bot response. The backend sends
 * `{ detail }`; a proxy may send `{ message }` or a non-JSON page. Returns
 * `null` when the body is not JSON or has neither field as a string.
 */
export const parseSlackBotErrorMessage = async (
  response: Response
): Promise<string | null> => {
  const body: unknown = await response.json().catch(() => null);
  if (typeof body !== "object" || body === null) {
    return null;
  }
  if ("detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  if ("message" in body && typeof body.message === "string") {
    return body.message;
  }
  return null;
};
