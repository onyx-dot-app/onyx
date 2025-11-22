import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { fetchSS } from "../utilsSS";

export async function fetchLLMProvidersSS() {
  // Test helper: allow Playwright runs to force an empty provider list so onboarding appears.
  if (process.env.PLAYWRIGHT_FORCE_EMPTY_LLM_PROVIDERS === "true") {
    return [];
  }
  const response = await fetchSS("/llm/provider");
  if (response.ok) {
    return (await response.json()) as LLMProviderDescriptor[];
  }
  return [];
}
