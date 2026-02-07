import { LLM_ADMIN_URL } from "@/app/admin/configuration/llm/constants";

export function setDefaultLlmModel(providerId: number, modelName: string) {
  const response = fetch(`${LLM_ADMIN_URL}/default`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      provider_id: providerId,
      model_name: modelName,
    }),
  });

  return response;
}
