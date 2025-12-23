import { LLMProviderName } from "../interfaces";
import { AnthropicForm } from "./AnthropicForm";
import { OpenAIForm } from "./OpenAIForm";
import { OllamaForm } from "./OllamaForm";
import { AzureForm } from "./AzureForm";
import { VertexAIForm } from "./VertexAIForm";
import { CustomLLMProviderUpdateForm } from "../CustomLLMProviderUpdateForm";

export const getFormForProvider = (providerName: LLMProviderName) => {
  switch (providerName) {
    case LLMProviderName.OPENAI:
      return <OpenAIForm />;
    case LLMProviderName.ANTHROPIC:
      return <AnthropicForm />;
    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaForm />;
    case LLMProviderName.AZURE:
      return <AzureForm />;
    case LLMProviderName.VERTEX_AI:
      return <VertexAIForm />;
    // default:
    //   return <CustomLLMProviderUpdateForm />;
  }
};
