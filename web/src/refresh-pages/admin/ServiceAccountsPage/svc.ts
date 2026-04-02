import type {
  APIKeyArgs,
  APIKey,
} from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";

const API_KEY_URL = "/api/admin/api-key";

export async function createApiKey(args: APIKeyArgs): Promise<Response> {
  return fetch(API_KEY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
}

export async function regenerateApiKey(apiKey: APIKey): Promise<Response> {
  return fetch(`${API_KEY_URL}/${apiKey.api_key_id}/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

export async function updateApiKey(
  apiKeyId: number,
  args: APIKeyArgs
): Promise<Response> {
  return fetch(`${API_KEY_URL}/${apiKeyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
}

export async function deleteApiKey(apiKeyId: number): Promise<Response> {
  return fetch(`${API_KEY_URL}/${apiKeyId}`, {
    method: "DELETE",
  });
}
