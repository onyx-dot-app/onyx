import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { fetchSS } from "../utilsSS";

export async function fetchLLMProvidersSS() {
  const response = await fetchSS("/llm/provider");
  if (response.ok) {
    return (await response.json()) as LLMProviderDescriptor[];
  }
  return [];
}
