import { LlmOverride } from "../hooks";

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
