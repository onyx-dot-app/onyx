import { ScopedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

const PERSONA_PROVIDER_ENDPOINT_PATTERN =
  /^\/api\/llm\/persona\/\d+\/providers$/;

export async function refreshLlmProviderCaches(
  mutate: ScopedMutator
): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.adminLlmProviders),
    mutate(SWR_KEYS.llmProviders),
    mutate(
      (key) =>
        typeof key === "string" && PERSONA_PROVIDER_ENDPOINT_PATTERN.test(key)
    ),
  ]);
}
