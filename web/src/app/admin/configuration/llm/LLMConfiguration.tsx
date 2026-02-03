"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { Callout } from "@/components/ui/callout";
import Text from "@/refresh-components/texts/Text";
import Title from "@/components/ui/title";
import { ThreeDotsLoader } from "@/components/Loading";
import { LLMProviderResponse, LLMProviderView } from "./interfaces";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { OpenAIForm } from "./forms/OpenAIForm";
import { AnthropicForm } from "./forms/AnthropicForm";
import { OllamaForm } from "./forms/OllamaForm";
import { AzureForm } from "./forms/AzureForm";
import { BedrockForm } from "./forms/BedrockForm";
import { VertexAIForm } from "./forms/VertexAIForm";
import { OpenRouterForm } from "./forms/OpenRouterForm";
import { getFormForExistingProvider } from "./forms/getForm";
import { CustomForm } from "./forms/CustomForm";

export function LLMConfiguration() {
  const { data: existingLLMProvidersResponse } = useSWR<
    LLMProviderResponse<LLMProviderView>
  >(LLM_PROVIDERS_ADMIN_URL, errorHandlingFetcher);

  if (!existingLLMProvidersResponse) {
    return <ThreeDotsLoader />;
  }

  const existingLlmProviders = existingLLMProvidersResponse.providers;
  const defaultProviderId =
    existingLLMProvidersResponse.default_text?.provider_id;
  const isFirstProvider = existingLlmProviders.length === 0;

  return (
    <>
      <Title className="mb-2">Enabled LLM Providers</Title>

      {existingLlmProviders.length > 0 ? (
        <>
          <Text as="p" className="mb-4">
            If multiple LLM providers are enabled, the default provider will be
            used for all &quot;Default&quot; Assistants. For user-created
            Assistants, you can select the LLM provider/model that best fits the
            use case!
          </Text>
          <div className="flex flex-col gap-y-4">
            {[...existingLlmProviders]
              .sort((a, b) => {
                if (a.id === defaultProviderId && b.id !== defaultProviderId)
                  return -1;
                if (a.id !== defaultProviderId && b.id === defaultProviderId)
                  return 1;
                return 0;
              })
              .map((llmProvider) => (
                <div key={llmProvider.id}>
                  {getFormForExistingProvider(
                    llmProvider,
                    existingLLMProvidersResponse.default_text ?? undefined
                  )}
                </div>
              ))}
          </div>
        </>
      ) : (
        <Callout type="warning" title="No LLM providers configured yet">
          Please set one up below in order to start using Onyx!
        </Callout>
      )}

      <Title className="mb-2 mt-6">Add LLM Provider</Title>
      <Text as="p" className="mb-4">
        Add a new LLM provider by either selecting from one of the default
        providers or by specifying your own custom LLM provider.
      </Text>

      <div className="flex flex-col gap-y-4">
        <OpenAIForm shouldMarkAsDefault={isFirstProvider} />
        <AnthropicForm shouldMarkAsDefault={isFirstProvider} />
        <OllamaForm shouldMarkAsDefault={isFirstProvider} />
        <AzureForm shouldMarkAsDefault={isFirstProvider} />
        <BedrockForm shouldMarkAsDefault={isFirstProvider} />
        <VertexAIForm shouldMarkAsDefault={isFirstProvider} />
        <OpenRouterForm shouldMarkAsDefault={isFirstProvider} />

        <CustomForm shouldMarkAsDefault={isFirstProvider} />
      </div>
    </>
  );
}
