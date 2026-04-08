import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import AnthropicModal from "@/sections/modals/llmConfig/AnthropicModal";
import OpenAIModal from "@/sections/modals/llmConfig/OpenAIModal";
import OllamaModal from "@/sections/modals/llmConfig/OllamaModal";
import AzureModal from "@/sections/modals/llmConfig/AzureModal";
import VertexAIModal from "@/sections/modals/llmConfig/VertexAIModal";
import OpenRouterModal from "@/sections/modals/llmConfig/OpenRouterModal";
import CustomModal from "@/sections/modals/llmConfig/CustomModal";
import BedrockModal from "@/sections/modals/llmConfig/BedrockModal";
import LMStudioModal from "@/sections/modals/llmConfig/LMStudioModal";
import LiteLLMProxyModal from "@/sections/modals/llmConfig/LiteLLMProxyModal";
import BifrostModal from "@/sections/modals/llmConfig/BifrostModal";
import OpenAICompatibleModal from "@/sections/modals/llmConfig/OpenAICompatibleModal";

export function getModalForExistingProvider(
  provider: LLMProviderView,
  onOpenChange?: (open: boolean) => void,
  defaultModelName?: string
) {
  const props = {
    existingLlmProvider: provider,
    onOpenChange,
    defaultModelName,
  };

  const hasCustomConfig = provider.custom_config != null;

  switch (provider.provider) {
    // These providers don't use custom_config themselves, so a non-null
    // custom_config means the provider was created via CustomModal.
    case LLMProviderName.OPENAI:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <OpenAIModal {...props} />
      );
    case LLMProviderName.ANTHROPIC:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <AnthropicModal {...props} />
      );
    case LLMProviderName.AZURE:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <AzureModal {...props} />
      );
    case LLMProviderName.OPENROUTER:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <OpenRouterModal {...props} />
      );

    // These providers legitimately store settings in custom_config,
    // so always use their dedicated modals.
    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaModal {...props} />;
    case LLMProviderName.VERTEX_AI:
      return <VertexAIModal {...props} />;
    case LLMProviderName.BEDROCK:
      return <BedrockModal {...props} />;
    case LLMProviderName.LM_STUDIO:
      return <LMStudioModal {...props} />;
    case LLMProviderName.LITELLM_PROXY:
      return <LiteLLMProxyModal {...props} />;
    case LLMProviderName.BIFROST:
      return <BifrostModal {...props} />;
    case LLMProviderName.OPENAI_COMPATIBLE:
      return <OpenAICompatibleModal {...props} />;
    default:
      return <CustomModal {...props} />;
  }
}
