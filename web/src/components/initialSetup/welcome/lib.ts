import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { User } from "@/lib/types";

const DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY = "defaultLlmProviderTestComplete";

function checkDefaultLLMProviderTestComplete() {
  return (
    localStorage.getItem(DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY) === "true"
  );
}

function setDefaultLLMProviderTestComplete() {
  localStorage.setItem(DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY, "true");
}

function shouldCheckDefaultLLMProvider(user: User | null) {
  return (
    !checkDefaultLLMProviderTestComplete() && (!user || user.role === "admin")
  );
}

export async function checkLlmProvider(user: User | null) {
  /* NOTE: should only be called on the client side, after initial render */
  const checkDefault = shouldCheckDefaultLLMProvider(user);

  const tasks = [
    fetch("/api/llm/provider"),
    fetch("/api/admin/llm/built-in/options"),
    checkDefault
      ? fetch("/api/admin/llm/test/default", { method: "POST" })
      : (async () => null)(),
  ];
  const [providerResponse, optionsResponse, defaultCheckResponse] =
    await Promise.all(tasks);

  let providers: LLMProviderView[] = [];
  if (providerResponse?.ok) {
    providers = await providerResponse.json();
  }

  let options: WellKnownLLMProviderDescriptor[] = [];
  if (optionsResponse?.ok) {
    options = await optionsResponse.json();
  }

  let defaultCheckSuccessful =
    !checkDefault || defaultCheckResponse?.ok || false;
  if (defaultCheckSuccessful) {
    setDefaultLLMProviderTestComplete();
  }

  return { providers, options, defaultCheckSuccessful };
}
