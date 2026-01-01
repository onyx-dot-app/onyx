import { LLMProviderName, LLMProviderView } from "../interfaces";
import { AnthropicForm } from "./AnthropicForm";
import { OpenAIForm } from "./OpenAIForm";
import { OllamaForm } from "./OllamaForm";
import { AzureForm } from "./AzureForm";
import { VertexAIForm } from "./VertexAIForm";
import { OpenRouterForm } from "./OpenRouterForm";
import { CustomForm } from "./CustomForm";
import { BedrockForm } from "./BedrockForm";

export function detectIfRealOpenAIProvider(provider: LLMProviderView) {
  return (
    provider.provider === LLMProviderName.OPENAI &&
    provider.api_key &&
    !provider.api_base &&
    Object.keys(provider.custom_config || {}).length === 0
  );
}

export const getFormForExistingProvider = (provider: LLMProviderView) => {
  switch (provider.provider) {
    case LLMProviderName.OPENAI:
      // "openai" as a provider name can be used for litellm proxy / any OpenAI-compatible provider
      if (detectIfRealOpenAIProvider(provider)) {
        return <OpenAIForm existingLlmProvider={provider} />;
      } else {
        return <CustomForm existingLlmProvider={provider} />;
      }
    case LLMProviderName.ANTHROPIC:
      return <AnthropicForm existingLlmProvider={provider} />;
    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaForm existingLlmProvider={provider} />;
    case LLMProviderName.AZURE:
      return <AzureForm existingLlmProvider={provider} />;
    case LLMProviderName.VERTEX_AI:
      return <VertexAIForm existingLlmProvider={provider} />;
    case LLMProviderName.BEDROCK:
      return <BedrockForm existingLlmProvider={provider} />;
    case LLMProviderName.OPENROUTER:
      return <OpenRouterForm existingLlmProvider={provider} />;
    default:
      return <CustomForm existingLlmProvider={provider} />;
  }
};
