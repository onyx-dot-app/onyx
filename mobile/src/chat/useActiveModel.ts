import { resolveDefaultModel } from "@/lib/languageModels";
import { useLlmProviders } from "@/query/llmProviders";
import { useChatSessionStore } from "@/state/chatSessionStore";
import type { LLMProviderDescriptor, SelectedModel } from "@/lib/types";

// Shared active-model derivation for the composer's input bar + model selector.
// Both surfaces resolve the same thing: the session's explicitly-selected model,
// falling back to the workspace-resolved default. Centralized here so the
// resolution + fallback stay identical across the two call sites.
export interface ActiveModelResult {
  /** Configured providers (empty until they load). */
  providers: LLMProviderDescriptor[];
  /** True while the providers query is still loading. */
  isLoading: boolean;
  /** Workspace-resolved default model (null when nothing is available). */
  defaultModel: SelectedModel | null;
  /** The session's explicitly-picked model, if any. */
  selectedModel: SelectedModel | undefined;
  /** The model in effect: selectedModel ?? defaultModel. */
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
