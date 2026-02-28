"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { toast } from "@/hooks/useToast";
import {
  useAdminLLMProviders,
  useWellKnownLLMProviders,
} from "@/hooks/useLLMProviders";
import { ThreeDotsLoader } from "@/components/Loading";
import { Content, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgCpu, SvgArrowExchange, SvgSettings, SvgTrash } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import {
  getProviderDisplayName,
  getProviderIcon,
  getProviderProductName,
} from "@/lib/llmConfig/providers";
import { deleteLlmProvider, setDefaultLlmModel } from "@/lib/llmConfig/svc";
import Text from "@/refresh-components/texts/Text";
import { Horizontal as HorizontalInput } from "@/layouts/input-layouts";
import Card from "@/refresh-components/cards/Card";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Message from "@/refresh-components/messages/Message";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import Separator from "@/refresh-components/Separator";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";
import { getModalForExistingProvider } from "@/sections/modals/llmConfig/getModal";
import { OpenAIModal } from "@/sections/modals/llmConfig/OpenAIModal";
import { AnthropicModal } from "@/sections/modals/llmConfig/AnthropicModal";
import { OllamaModal } from "@/sections/modals/llmConfig/OllamaModal";
import { AzureModal } from "@/sections/modals/llmConfig/AzureModal";
import { BedrockModal } from "@/sections/modals/llmConfig/BedrockModal";
import { VertexAIModal } from "@/sections/modals/llmConfig/VertexAIModal";
import { OpenRouterModal } from "@/sections/modals/llmConfig/OpenRouterModal";
import { CustomModal } from "@/sections/modals/llmConfig/CustomModal";
import { Section } from "@/layouts/general-layouts";

// ============================================================================
// Provider form mapping (keyed by provider name from the API)
// ============================================================================

const PROVIDER_MODAL_MAP: Record<
  string,
  (
    shouldMarkAsDefault: boolean,
    open: boolean,
    onOpenChange: (open: boolean) => void
  ) => React.ReactNode
> = {
  openai: (d, open, onOpenChange) => (
    <OpenAIModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  anthropic: (d, open, onOpenChange) => (
    <AnthropicModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  ollama_chat: (d, open, onOpenChange) => (
    <OllamaModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  azure: (d, open, onOpenChange) => (
    <AzureModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  bedrock: (d, open, onOpenChange) => (
    <BedrockModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  vertex_ai: (d, open, onOpenChange) => (
    <VertexAIModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
  openrouter: (d, open, onOpenChange) => (
    <OpenRouterModal
      shouldMarkAsDefault={d}
      open={open}
      onOpenChange={onOpenChange}
    />
  ),
};

// ============================================================================
// ExistingProviderCard — card for configured (existing) providers
// ============================================================================

interface ExistingProviderCardProps {
  provider: LLMProviderView;
  isDefault: boolean;
  isLastProvider: boolean;
}

function ExistingProviderCard({
  provider,
  isDefault,
  isLastProvider,
}: ExistingProviderCardProps) {
  const { mutate } = useSWRConfig();
  const [isOpen, setIsOpen] = useState(false);
  const deleteModal = useCreateModal();

  const handleDelete = async () => {
    try {
      await deleteLlmProvider(provider.id);
      mutate(LLM_PROVIDERS_ADMIN_URL);
      deleteModal.toggle(false);
      toast.success("Provider deleted successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to delete provider: ${message}`);
    }
  };

  return (
    <>
      {deleteModal.isOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={`Delete ${provider.name}`}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button variant="danger" onClick={handleDelete}>
              Delete
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text text03>
              All LLM models from provider <b>{provider.name}</b> will be
              removed and unavailable for future chats. Chat history will be
              preserved.
            </Text>
            {isLastProvider && (
              <Text text03>
                Connect another provider to continue using chats.
              </Text>
            )}
          </Section>
        </ConfirmationModalLayout>
      )}

      <Hoverable.Root group="ExistingProviderCard">
        <Card padding={0.5}>
          <ContentAction
            icon={getProviderIcon(provider.provider)}
            title={provider.name}
            description={getProviderDisplayName(provider.provider)}
            sizePreset="main-content"
            variant="section"
            tag={isDefault ? { title: "Default", color: "blue" } : undefined}
            rightChildren={
              <Section flexDirection="row" gap={0} alignItems="start">
                <Hoverable.Item
                  group="ExistingProviderCard"
                  variant="opacity-on-hover"
                >
                  <Button
                    icon={SvgTrash}
                    prominence="tertiary"
                    aria-label="Delete provider"
                    onClick={() => deleteModal.toggle(true)}
                  />
                </Hoverable.Item>
                <Button
                  icon={SvgSettings}
                  prominence="tertiary"
                  aria-label="Edit provider"
                  onClick={() => setIsOpen(true)}
                />
              </Section>
            }
          />
          {getModalForExistingProvider(provider, isOpen, setIsOpen)}
        </Card>
      </Hoverable.Root>
    </>
  );
}

// ============================================================================
// NewProviderCard — card for the "Add Provider" list
// ============================================================================

interface NewProviderCardProps {
  provider: WellKnownLLMProviderDescriptor;
  isFirstProvider: boolean;
  formFn: (
    shouldMarkAsDefault: boolean,
    open: boolean,
    onOpenChange: (open: boolean) => void
  ) => React.ReactNode;
}

function NewProviderCard({
  provider,
  isFirstProvider,
  formFn,
}: NewProviderCardProps) {
  const [isOpen, setIsOpen] = useState(false);

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
            onClick={() => setIsOpen(true)}
          >
            Connect
          </Button>
        }
      />
      {formFn(isFirstProvider, isOpen, setIsOpen)}
    </Card>
  );
}

// ============================================================================
// NewCustomProviderCard — card for adding a custom LLM provider
// ============================================================================

interface NewCustomProviderCardProps {
  isFirstProvider: boolean;
}

function NewCustomProviderCard({
  isFirstProvider,
}: NewCustomProviderCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Card variant="secondary" padding={0.5}>
      <ContentAction
        icon={getProviderIcon("custom")}
        title={getProviderProductName("custom")}
        description={getProviderDisplayName("custom")}
        sizePreset="main-content"
        variant="section"
        rightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            onClick={() => setIsOpen(true)}
          >
            Set Up
          </Button>
        }
      />
      <CustomModal
        shouldMarkAsDefault={isFirstProvider}
        open={isOpen}
        onOpenChange={setIsOpen}
      />
    </Card>
  );
}

// ============================================================================
// LLMConfigurationPage — main page component
// ============================================================================

export default function LLMConfigurationPage() {
  const { mutate } = useSWRConfig();
  const { llmProviders: existingLlmProviders, defaultText } =
    useAdminLLMProviders();
  const { wellKnownLLMProviders } = useWellKnownLLMProviders();

  if (!existingLlmProviders) {
    return <ThreeDotsLoader />;
  }

  const hasProviders = existingLlmProviders.length > 0;
  const isFirstProvider = !hasProviders;

  // Pre-sort providers so the default appears first
  const sortedProviders = [...existingLlmProviders].sort((a, b) => {
    const aIsDefault = defaultText?.provider_id === a.id;
    const bIsDefault = defaultText?.provider_id === b.id;
    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    return 0;
  });

  // Pre-filter to providers that have at least one visible model
  const providersWithVisibleModels = existingLlmProviders
    .map((provider) => ({
      provider,
      visibleModels: provider.model_configurations.filter((m) => m.is_visible),
    }))
    .filter(({ visibleModels }) => visibleModels.length > 0);

  // Default model logic — use the global default from the API response
  const currentDefaultValue = defaultText
    ? `${defaultText.provider_id}:${defaultText.model_name}`
    : undefined;

  async function handleDefaultModelChange(compositeValue: string) {
    const separatorIndex = compositeValue.indexOf(":");
    const providerId = Number(compositeValue.slice(0, separatorIndex));
    const modelName = compositeValue.slice(separatorIndex + 1);

    try {
      await setDefaultLlmModel(providerId, modelName);
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
        {hasProviders ? (
          <Card>
            <HorizontalInput
              title="Default Model"
              description="This model will be used by Onyx by default in your chats."
              nonInteractive
              center
            >
              <InputSelect
                value={currentDefaultValue}
                onValueChange={handleDefaultModelChange}
              >
                <InputSelect.Trigger placeholder="Select a default model" />
                <InputSelect.Content>
                  {providersWithVisibleModels.map(
                    ({ provider, visibleModels }) => (
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
                    )
                  )}
                </InputSelect.Content>
              </InputSelect>
            </HorizontalInput>
          </Card>
        ) : (
          <Message
            info
            large
            icon
            close={false}
            text="Set up an LLM provider to start chatting."
            className="w-full"
          />
        )}

        {/* ── Available Providers (only when providers exist) ── */}
        {hasProviders && (
          <>
            <GeneralLayouts.Section
              gap={0.75}
              height="fit"
              alignItems="stretch"
              justifyContent="start"
            >
              <Content
                title="Available Providers"
                sizePreset="main-content"
                variant="section"
              />

              <div className="flex flex-col gap-2">
                {sortedProviders.map((provider) => (
                  <ExistingProviderCard
                    key={provider.id}
                    provider={provider}
                    isDefault={defaultText?.provider_id === provider.id}
                    isLastProvider={sortedProviders.length === 1}
                  />
                ))}
              </div>
            </GeneralLayouts.Section>

            <Separator noPadding />
          </>
        )}

        {/* ── Add Provider (always visible) ── */}
        <GeneralLayouts.Section
          gap={0.75}
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

          <div className="grid grid-cols-2 gap-2">
            {wellKnownLLMProviders?.map((provider) => {
              const formFn = PROVIDER_MODAL_MAP[provider.name];
              if (!formFn) {
                toast.error(
                  `No modal mapping for provider "${provider.name}".`
                );
                return null;
              }
              return (
                <NewProviderCard
                  key={provider.name}
                  provider={provider}
                  isFirstProvider={isFirstProvider}
                  formFn={formFn}
                />
              );
            })}
            <NewCustomProviderCard isFirstProvider={isFirstProvider} />
          </div>
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
