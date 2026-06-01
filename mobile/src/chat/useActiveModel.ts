import { resolveDefaultModel } from "@/lib/languageModels";
import { useLlmProviders } from "@/query/llmProviders";
import { useChatSessionStore } from "@/state/chatSessionStore";
import type { LLMProviderDescriptor, SelectedModel } from "@/lib/types";

// Shared active-model derivation (session's selected model, falling back to the
// workspace default) for the input bar + model selector.
export interface ActiveModelResult {
  providers: LLMProviderDescriptor[];
  isLoading: boolean;
  defaultModel: SelectedModel | null;
  selectedModel: SelectedModel | undefined;
  activeModel: SelectedModel | null;
}

export function useActiveModel(sessionId: string): ActiveModelResult {
  const { data, isLoading } = useLlmProviders();
  const providers = data?.providers ?? [];
  const defaultModel = resolveDefaultModel(providers, data?.default_text ?? null);

  const selectedModel = useChatSessionStore(
    (s) => s.sessions.get(sessionId)?.selectedModel,
  );

  const activeModel = selectedModel ?? defaultModel;

  return { providers, isLoading, defaultModel, selectedModel, activeModel };
}
