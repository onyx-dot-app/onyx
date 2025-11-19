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
