import { LLMProviderResponse, VisionProvider } from "@/interfaces/llm";
import { LLM_ADMIN_URL } from "@/lib/llmConfig/constants";

export async function fetchVisionProviders(): Promise<VisionProvider[]> {
  const response = await fetch("/api/admin/llm/vision-providers", {
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch vision providers: ${await response.text()}`
    );
  }
  const data = (await response.json()) as LLMProviderResponse<VisionProvider>;
  return data.providers;
}

export async function setDefaultVisionProvider(
  providerId: number,
  visionModel: string
): Promise<void> {
  const response = await fetch(`${LLM_ADMIN_URL}/default-vision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      provider_id: providerId,
      model_name: visionModel,
    }),
  });

  if (!response.ok) {
    const errorMsg = await response.text();
    throw new Error(errorMsg);
  }
}
