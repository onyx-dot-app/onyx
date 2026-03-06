import { ScopedMutator } from "swr";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";

const PERSONA_PROVIDER_ENDPOINT_PATTERN =
  /^\/api\/llm\/persona\/\d+\/providers$/;

export async function refreshLlmProviderCaches(
  mutate: ScopedMutator
): Promise<void> {
  await Promise.all([
    mutate(LLM_PROVIDERS_ADMIN_URL),
    mutate("/api/llm/provider"),
    mutate(
      (key) =>
        typeof key === "string" && PERSONA_PROVIDER_ENDPOINT_PATTERN.test(key)
    ),
  ]);
}
