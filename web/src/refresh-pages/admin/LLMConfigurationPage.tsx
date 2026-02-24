"use client";

import { useRef } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useWellKnownLLMProviders } from "@/hooks/useLLMProviders";
import { ThreeDotsLoader } from "@/components/Loading";
import { Content, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgCpu, SvgArrowExchange, SvgSettings } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import {
  getProviderDisplayName,
  getProviderIcon,
  getProviderProductName,
} from "@/lib/llmConfig/providers";
import { setDefaultLLMProvider } from "@/lib/llmConfig/svc";
import { Horizontal as HorizontalInput } from "@/layouts/input-layouts";
import Card from "@/refresh-components/cards/Card";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Separator from "@/refresh-components/Separator";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";
import { getFormForExistingProvider } from "@/app/admin/configuration/llm/forms/getForm";
import { OpenAIForm } from "@/app/admin/configuration/llm/forms/OpenAIForm";
import { AnthropicForm } from "@/app/admin/configuration/llm/forms/AnthropicForm";
import { OllamaForm } from "@/app/admin/configuration/llm/forms/OllamaForm";
import { AzureForm } from "@/app/admin/configuration/llm/forms/AzureForm";
import { BedrockForm } from "@/app/admin/configuration/llm/forms/BedrockForm";
import { VertexAIForm } from "@/app/admin/configuration/llm/forms/VertexAIForm";
import { OpenRouterForm } from "@/app/admin/configuration/llm/forms/OpenRouterForm";
import { CustomForm } from "@/app/admin/configuration/llm/forms/CustomForm";

// ============================================================================
// Provider form mapping (keyed by provider name from the API)
// ============================================================================

const PROVIDER_FORM_MAP: Record<
  string,
  (shouldMarkAsDefault: boolean) => React.ReactNode
> = {
  openai: (d) => <OpenAIForm shouldMarkAsDefault={d} />,
  anthropic: (d) => <AnthropicForm shouldMarkAsDefault={d} />,
  ollama_chat: (d) => <OllamaForm shouldMarkAsDefault={d} />,
  azure: (d) => <AzureForm shouldMarkAsDefault={d} />,
  bedrock: (d) => <BedrockForm shouldMarkAsDefault={d} />,
  vertex_ai: (d) => <VertexAIForm shouldMarkAsDefault={d} />,
  openrouter: (d) => <OpenRouterForm shouldMarkAsDefault={d} />,
};

// ============================================================================
// ExistingProviderCard — card for configured (existing) providers
// ============================================================================

interface ExistingProviderCardProps {
  provider: LLMProviderView;
  children: React.ReactNode;
}

function ExistingProviderCard({
  provider,
  children,
}: ExistingProviderCardProps) {
  const triggerRef = useRef<HTMLDivElement>(null);

  function handleEdit() {
    const button = triggerRef.current?.querySelector("button");
    button?.click();
  }

  return (
    <Card padding={0.5}>
      <ContentAction
        icon={getProviderIcon(provider.provider)}
        title={provider.name}
        description={getProviderDisplayName(provider.provider)}
        sizePreset="main-content"
        variant="section"
        tag={
          provider.is_default_provider
            ? { title: "Default", color: "blue" }
            : { title: "Enabled", color: "green" }
        }
        rightChildren={
          <Button
            icon={SvgSettings}
            prominence="tertiary"
            onClick={handleEdit}
          />
        }
      />
      <div ref={triggerRef} className="hidden">
        {children}
      </div>
    </Card>
  );
}

// ============================================================================
// NewProviderCard — card for the "Add Provider" list
// ============================================================================

interface NewProviderCardProps {
  provider: WellKnownLLMProviderDescriptor;
  children: React.ReactNode;
}

function NewProviderCard({ provider, children }: NewProviderCardProps) {
  const triggerRef = useRef<HTMLDivElement>(null);

  function handleConnect() {
    const button = triggerRef.current?.querySelector("button");
    button?.click();
  }

  return (
    <Card variant="secondary" padding={0.5}>
      <ContentAction
        icon={getProviderIcon(provider.name)}
        title={getProviderProductName(provider.name)}
        description={getProviderDisplayName(provider.name)}
        sizePreset="main-content"
        variant="section"
        rightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            onClick={handleConnect}
          >
            Connect
          </Button>
        }
      />
      <div ref={triggerRef} className="hidden">
        {children}
      </div>
    </Card>
  );
}

// ============================================================================
// LLMConfigurationPage — main page component
// ============================================================================

export default function LLMConfigurationPage() {
  const { mutate } = useSWRConfig();
  const { data: existingLlmProviders } = useSWR<LLMProviderView[]>(
    LLM_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher
  );
  const { wellKnownLLMProviders } = useWellKnownLLMProviders();

  if (!existingLlmProviders) {
    return <ThreeDotsLoader />;
  }

  const hasProviders = existingLlmProviders.length > 0;
  const isFirstProvider = !hasProviders;

  // Default model logic
  const defaultProvider = existingLlmProviders.find(
    (p) => p.is_default_provider
  );
  const currentDefaultValue = defaultProvider
    ? `${defaultProvider.id}:${defaultProvider.default_model_name}`
    : undefined;

  async function handleDefaultModelChange(compositeValue: string) {
    try {
      await setDefaultLLMProvider(compositeValue);
      mutate(LLM_PROVIDERS_ADMIN_URL);
      toast.success("Default model updated successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to set default model: ${message}`);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={SvgCpu} title="LLM Models" separator />

      <SettingsLayouts.Body>
        {/* ── Default Model Card (only when providers exist) ── */}
        {hasProviders && (
          <Card>
            <HorizontalInput
              title="Default Model"
              description="This model will be used by Onyx by default in your chats."
              nonInteractive
            >
              <InputSelect
                value={currentDefaultValue}
                onValueChange={handleDefaultModelChange}
              >
                <InputSelect.Trigger placeholder="Select a default model" />
                <InputSelect.Content>
                  {existingLlmProviders.map((provider) => {
                    const visibleModels = provider.model_configurations.filter(
                      (m) => m.is_visible
                    );
                    if (visibleModels.length === 0) return null;

                    return (
                      <InputSelect.Group key={provider.id}>
                        <InputSelect.Label>{provider.name}</InputSelect.Label>
                        {visibleModels.map((model) => (
                          <InputSelect.Item
                            key={`${provider.id}:${model.name}`}
                            value={`${provider.id}:${model.name}`}
                          >
                            {model.display_name || model.name}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Group>
                    );
                  })}
                </InputSelect.Content>
              </InputSelect>
            </HorizontalInput>
          </Card>
        )}

        {/* ── Available Providers (only when providers exist) ── */}
        {hasProviders && (
          <>
            <GeneralLayouts.Section
              gap={0.5}
              height="fit"
              alignItems="stretch"
              justifyContent="start"
            >
              <Content
                title="Available Providers"
                sizePreset="main-content"
                variant="section"
              />

              <div className="flex flex-col gap-4">
                {[...existingLlmProviders]
                  .sort((a, b) => {
                    if (a.is_default_provider && !b.is_default_provider)
                      return -1;
                    if (!a.is_default_provider && b.is_default_provider)
                      return 1;
                    return 0;
                  })
                  .map((provider) => (
                    <ExistingProviderCard key={provider.id} provider={provider}>
                      {getFormForExistingProvider(provider)}
                    </ExistingProviderCard>
                  ))}
              </div>
            </GeneralLayouts.Section>

            <Separator noPadding />
          </>
        )}

        {/* ── Add Provider (always visible) ── */}
        <GeneralLayouts.Section
          gap={0.5}
          height="fit"
          alignItems="stretch"
          justifyContent="start"
        >
          <Content
            title="Add Provider"
            description="Onyx supports both popular providers and self-hosted models."
            sizePreset="main-content"
            variant="section"
          />

          <div className="grid grid-cols-2 gap-4">
            {wellKnownLLMProviders?.map((provider) => {
              const formFn = PROVIDER_FORM_MAP[provider.name];
              if (!formFn) return null;
              return (
                <NewProviderCard key={provider.name} provider={provider}>
                  {formFn(isFirstProvider)}
                </NewProviderCard>
              );
            })}
            <NewProviderCard
              provider={{
                name: "custom",
                known_models: [],
                recommended_default_model: null,
              }}
            >
              <CustomForm shouldMarkAsDefault={isFirstProvider} />
            </NewProviderCard>
          </div>
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
