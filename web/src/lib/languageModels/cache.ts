import { ScopedMutator } from "swr";
import { toast } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { setDefaultLlmModel } from "@/lib/languageModels/svc";

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

export async function setDefaultLlmModelAndRefresh(
  providerId: number,
  modelName: string,
  mutate: ScopedMutator
): Promise<void> {
  try {
    await setDefaultLlmModel(providerId, modelName);
    await refreshLlmProviderCaches(mutate);
    toast.success("Default model updated successfully!");
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    toast.error(`Failed to set default model: ${message}`);
  }
}
