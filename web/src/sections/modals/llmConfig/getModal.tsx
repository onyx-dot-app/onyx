import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import { AnthropicModal } from "./AnthropicModal";
import { OpenAIModal } from "./OpenAIModal";
import { OllamaModal } from "./OllamaModal";
import { AzureModal } from "./AzureModal";
import { VertexAIModal } from "./VertexAIModal";
import { OpenRouterModal } from "./OpenRouterModal";
import { CustomModal } from "./CustomModal";
import { BedrockModal } from "./BedrockModal";

export function detectIfRealOpenAIProvider(provider: LLMProviderView) {
  return (
    provider.provider === LLMProviderName.OPENAI &&
    provider.api_key &&
    !provider.api_base &&
    Object.keys(provider.custom_config || {}).length === 0
  );
}

export function getModalForExistingProvider(
  provider: LLMProviderView,
  open?: boolean,
  onOpenChange?: (open: boolean) => void
) {
  const props = { existingLlmProvider: provider, open, onOpenChange };

  switch (provider.provider) {
    case LLMProviderName.OPENAI:
      // "openai" as a provider name can be used for litellm proxy / any OpenAI-compatible provider
      if (detectIfRealOpenAIProvider(provider)) {
        return <OpenAIModal {...props} />;
      } else {
        return <CustomModal {...props} />;
      }
    case LLMProviderName.ANTHROPIC:
      return <AnthropicModal {...props} />;
    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaModal {...props} />;
    case LLMProviderName.AZURE:
      return <AzureModal {...props} />;
    case LLMProviderName.VERTEX_AI:
      return <VertexAIModal {...props} />;
    case LLMProviderName.BEDROCK:
      return <BedrockModal {...props} />;
    case LLMProviderName.OPENROUTER:
      return <OpenRouterModal {...props} />;
    default:
      return <CustomModal {...props} />;
  }
}
