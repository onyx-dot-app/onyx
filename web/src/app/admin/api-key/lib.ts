import { CreateAPIKeyArgs, UpdateAPIKeyArgs, APIKey } from "./types";

export const createApiKey = async (createArgs: CreateAPIKeyArgs) => {
  return fetch("/api/admin/api-key", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(createArgs),
  });
};

export const regenerateApiKey = async (apiKey: APIKey) => {
  return fetch(`/api/admin/api-key/${apiKey.api_key_id}/regenerate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export const updateApiKey = async (
  apiKeyId: number,
  updateArgs: UpdateAPIKeyArgs
) => {
  return fetch(`/api/admin/api-key/${apiKeyId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(updateArgs),
  });
};

export const deleteApiKey = async (apiKeyId: number) => {
  return fetch(`/api/admin/api-key/${apiKeyId}`, {
    method: "DELETE",
  });
};
