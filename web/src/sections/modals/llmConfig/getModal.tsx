import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import AnthropicModal from "@/sections/modals/llmConfig/AnthropicModal";
import OpenAIModal from "@/sections/modals/llmConfig/OpenAIModal";
import OllamaModal from "@/sections/modals/llmConfig/OllamaModal";
import AzureModal from "@/sections/modals/llmConfig/AzureModal";
import VertexAIModal from "@/sections/modals/llmConfig/VertexAIModal";
import OpenRouterModal from "@/sections/modals/llmConfig/OpenRouterModal";
import AvianModal from "@/sections/modals/llmConfig/AvianModal";
import CustomModal from "@/sections/modals/llmConfig/CustomModal";
import BedrockModal from "@/sections/modals/llmConfig/BedrockModal";
import LMStudioForm from "@/sections/modals/llmConfig/LMStudioForm";
import LiteLLMProxyModal from "@/sections/modals/llmConfig/LiteLLMProxyModal";

function detectIfRealOpenAIProvider(provider: LLMProviderView) {
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
    case LLMProviderName.AVIAN:
      return <AvianModal {...props} />;
    case LLMProviderName.LM_STUDIO:
      return <LMStudioForm {...props} />;
    case LLMProviderName.LITELLM_PROXY:
      return <LiteLLMProxyModal {...props} />;
    default:
      return <CustomModal {...props} />;
  }
}
