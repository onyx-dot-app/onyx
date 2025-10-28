import { UserPersonalization } from "@/lib/types";

export async function setUserDefaultModel(
  model: string | null
): Promise<Response> {
  const response = await fetch(`/api/user/default-model`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ default_model: model }),
  });

  return response;
}

/**
 * Update the current user's personalization settings.
 */
export async function updateUserPersonalization(
  personalization: UserPersonalization
): Promise<Response> {
  return fetch(`/api/user/personalization`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(personalization),
  });
}
