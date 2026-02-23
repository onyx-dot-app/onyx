"use client";

import { useRef } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Content } from "@opal/layouts";
import { Button } from "@opal/components";
import {
  SvgCpu,
  SvgOpenai,
  SvgClaude,
  SvgOllama,
  SvgCloud,
  SvgAws,
  SvgOpenrouter,
  SvgArrowExchange,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Horizontal as HorizontalInput } from "@/layouts/input-layouts";
import Card from "@/refresh-components/cards/Card";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Separator from "@/refresh-components/Separator";
import { LLMProviderView } from "@/app/admin/configuration/llm/interfaces";
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
// Provider definitions for the "Add Provider" section
// ============================================================================

interface ProviderDefinition {
  name: string;
  icon: IconFunctionComponent;
  form: (shouldMarkAsDefault: boolean) => React.ReactNode;
}

const PROVIDER_DEFINITIONS: ProviderDefinition[] = [
  {
    name: "OpenAI",
    icon: SvgOpenai,
    form: (d) => <OpenAIForm shouldMarkAsDefault={d} />,
  },
  {
    name: "Anthropic",
    icon: SvgClaude,
    form: (d) => <AnthropicForm shouldMarkAsDefault={d} />,
  },
  {
    name: "Ollama",
    icon: SvgOllama,
    form: (d) => <OllamaForm shouldMarkAsDefault={d} />,
  },
  {
    name: "Microsoft Azure Cloud",
    icon: SvgCloud,
    form: (d) => <AzureForm shouldMarkAsDefault={d} />,
  },
  {
    name: "AWS Bedrock",
    icon: SvgAws,
    form: (d) => <BedrockForm shouldMarkAsDefault={d} />,
  },
  {
    name: "Google Cloud Vertex AI",
    icon: SvgCloud,
    form: (d) => <VertexAIForm shouldMarkAsDefault={d} />,
  },
  {
    name: "OpenRouter",
    icon: SvgOpenrouter,
    form: (d) => <OpenRouterForm shouldMarkAsDefault={d} />,
  },
  {
    name: "Custom LLM",
    icon: SvgCpu,
    form: (d) => <CustomForm shouldMarkAsDefault={d} />,
  },
];

// ============================================================================
// ProviderConnectCard — local component for the "Add Provider" list
// ============================================================================

interface ProviderConnectCardProps {
  name: string;
  icon: IconFunctionComponent;
  children: React.ReactNode;
}

function ProviderConnectCard({
  name,
  icon,
  children,
}: ProviderConnectCardProps) {
  const triggerRef = useRef<HTMLDivElement>(null);

  function handleConnect() {
    const button = triggerRef.current?.querySelector("button");
    button?.click();
  }

  return (
    <Card variant="secondary">
      <div className="flex items-center justify-between w-full">
        <Content
          icon={icon}
          title={name}
          sizePreset="main-content"
          variant="body"
        />
        <Button
          rightIcon={SvgArrowExchange}
          prominence="secondary"
          onClick={handleConnect}
        >
          Connect
        </Button>
      </div>
      {/* The form component renders its own card (hidden) + modal (portal).
          Portals render at the document root, so the modal remains visible. */}
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
    const separatorIndex = compositeValue.indexOf(":");
    const providerId = compositeValue.slice(0, separatorIndex);

    const response = await fetch(
      `${LLM_PROVIDERS_ADMIN_URL}/${providerId}/default`,
      { method: "POST" }
    );

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      toast.error(`Failed to set default model: ${errorMsg}`);
      return;
    }

    mutate(LLM_PROVIDERS_ADMIN_URL);
    toast.success("Default model updated successfully!");
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgCpu}
        title="LLM Configuration"
        description="Configure LLM providers and set the default model for your organization."
        separator
      />

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
                  if (!a.is_default_provider && b.is_default_provider) return 1;
                  return 0;
                })
                .map((provider) => (
                  <div key={provider.id}>
                    {getFormForExistingProvider(provider)}
                  </div>
                ))}
            </div>

            <Separator noPadding />
          </>
        )}

        {/* ── Add Provider (always visible) ── */}
        <Content
          title="Add Provider"
          description="Onyx supports both popular providers and self-hosted models."
          sizePreset="main-content"
          variant="section"
        />

        <div className="grid grid-cols-2 gap-4">
          {PROVIDER_DEFINITIONS.map((provider) => (
            <ProviderConnectCard
              key={provider.name}
              name={provider.name}
              icon={provider.icon}
            >
              {provider.form(isFirstProvider)}
            </ProviderConnectCard>
          ))}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
