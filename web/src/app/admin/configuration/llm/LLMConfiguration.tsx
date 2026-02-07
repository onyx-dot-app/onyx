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
import { DefaultModelSelector } from "./forms/components/DefaultModel";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Separator from "@/refresh-components/Separator";
import { useLlmManager } from "@/lib/hooks";

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
  const defaultLlmModel =
    existingLLMProvidersResponse.default_text ?? undefined;
  const isFirstProvider = existingLlmProviders.length === 0;

  const { updateDefaultLlmModel } = useLlmManager();

  return (
    <>
      {existingLlmProviders.length > 0 ? (
        <>
          <DefaultModelSelector
            existingLlmProviders={existingLlmProviders}
            defaultLlmModel={defaultLlmModel ?? null}
            onModelChange={(provider_id, model_name) =>
              updateDefaultLlmModel({ provider_id, model_name })
            }
          />

          <GeneralLayouts.Section
            flexDirection="column"
            justifyContent="start"
            alignItems="start"
          >
            <Text headingH3>Available Providers</Text>
            {[...existingLlmProviders]
              .sort((a, b) => {
                if (a.id === defaultProviderId && b.id !== defaultProviderId)
                  return -1;
                if (a.id !== defaultProviderId && b.id === defaultProviderId)
                  return 1;
                return 0;
              })
              .map((llmProvider) => getFormForExistingProvider(llmProvider))}
          </GeneralLayouts.Section>

          <Separator />
        </>
      ) : (
        <Callout type="warning" title="No LLM providers configured yet">
          Please set one up below in order to start using Onyx!
        </Callout>
      )}

      <GeneralLayouts.Section
        flexDirection="column"
        justifyContent="start"
        alignItems="start"
        gap={0}
      >
        <Text headingH3>Add Provider</Text>
        <Text as="p" secondaryBody text03>
          Onyx supports both popular providers and self-hosted models.
        </Text>
      </GeneralLayouts.Section>

      <div className="grid grid-cols-2 gap-4">
        <OpenAIForm shouldMarkAsDefault={isFirstProvider} />
        <AnthropicForm shouldMarkAsDefault={isFirstProvider} />
        <OllamaForm shouldMarkAsDefault={isFirstProvider} />
        <VertexAIForm shouldMarkAsDefault={isFirstProvider} />
        <AzureForm shouldMarkAsDefault={isFirstProvider} />
        <BedrockForm shouldMarkAsDefault={isFirstProvider} />
        <OpenRouterForm shouldMarkAsDefault={isFirstProvider} />

        <CustomForm shouldMarkAsDefault={isFirstProvider} />
      </div>
    </>
  );
}
