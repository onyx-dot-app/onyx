import { LLMProviderName, LLMProviderView } from "../interfaces";
import { AnthropicForm } from "./AnthropicForm";
import { OpenAIForm } from "./OpenAIForm";
import { OllamaForm } from "./OllamaForm";
import { AzureForm } from "./AzureForm";
import { VertexAIForm } from "./VertexAIForm";
import { OpenRouterForm } from "./OpenRouterForm";
import { CustomForm } from "./CustomForm";
import { BedrockForm } from "./BedrockForm";

export const getFormForExistingProvider = (provider: LLMProviderView) => {
  console.log("provider", provider);
  switch (provider.provider) {
    case LLMProviderName.OPENAI:
      return <OpenAIForm existingLlmProvider={provider} />;
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
