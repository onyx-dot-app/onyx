"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { toast } from "@/hooks/useToast";
import { useAdminLLMProviders } from "@/hooks/useLLMProviders";
import { ThreeDotsLoader } from "@/components/Loading";
import { Content, Card as CardLayout, InputHorizontal } from "@opal/layouts";
import {
  Button,
  Divider,
  MessageCard,
  SelectCard,
  Text,
  Card,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgArrowExchange, SvgSettings, SvgTrash } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { getProvider } from "@/lib/llmConfig";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { deleteLlmProvider, setDefaultLlmModel } from "@/lib/llmConfig/svc";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import { Section } from "@/layouts/general-layouts";
import { markdown } from "@opal/utils";

const route = ADMIN_ROUTES.LLM_MODELS;

// ============================================================================
// Provider form mapping (keyed by provider name from the API)
// ============================================================================

// Static list of well-known providers rendered in the "Add Provider" grid.
// Must match the backend's WELL_KNOWN_PROVIDER_NAMES (minus any that lack a
// dedicated modal). Order here controls display order.
const PROVIDER_DISPLAY_ORDER: string[] = [
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.VERTEX_AI,
  LLMProviderName.BEDROCK,
  LLMProviderName.AZURE,
  LLMProviderName.LITELLM_PROXY,
  LLMProviderName.OLLAMA_CHAT,
  LLMProviderName.OPENROUTER,
  LLMProviderName.LM_STUDIO,
  LLMProviderName.BIFROST,
  LLMProviderName.OPENAI_COMPATIBLE,
];

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
      await deleteLlmProvider(provider.id, isLastProvider);
      await refreshLlmProviderCaches(mutate);
      deleteModal.toggle(false);
      toast.success("Provider deleted successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to delete provider: ${message}`);
    }
  };

  const { icon, companyName, Modal } = getProvider(provider.provider, provider);

  return (
    <>
      {isOpen && (
        <Modal existingLlmProvider={provider} onOpenChange={setIsOpen} />
      )}

      {deleteModal.isOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={markdown(`Delete *${provider.name}*`)}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={isDefault && !isLastProvider}
            >
              Delete
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            {isDefault && !isLastProvider ? (
              <Text font="main-ui-body" color="text-03">
                Cannot delete the default provider. Select another provider as
                the default prior to deleting this one.
              </Text>
            ) : (
              <>
                <Text font="main-ui-body" color="text-03">
                  {markdown(
                    `All LLM models from provider **${provider.name}** will be removed and unavailable for future chats. Chat history will be preserved.`
                  )}
                </Text>
                {isLastProvider && (
                  <Text font="main-ui-body" color="text-03">
                    Connect another provider to continue using chats.
                  </Text>
                )}
              </>
            )}
          </Section>
        </ConfirmationModalLayout>
      )}

      <Hoverable.Root
        group="ExistingProviderCard"
        interaction={deleteModal.isOpen ? "hover" : "rest"}
      >
        <SelectCard
          state="filled"
          padding="sm"
          rounding="lg"
          onClick={() => setIsOpen(true)}
        >
          <CardLayout.Header
            headerPadding="sm"
            headerChildren={
              <Content
                icon={icon}
                title={provider.name}
                description={companyName}
                sizePreset="main-ui"
                variant="section"
                tag={
                  isDefault ? { title: "Default", color: "blue" } : undefined
                }
              />
            }
            topRightChildren={
              <div className="flex flex-row">
                <Hoverable.Item
                  group="ExistingProviderCard"
                  variant="opacity-on-hover"
                >
                  <Button
                    icon={SvgTrash}
                    prominence="tertiary"
                    aria-label={`Delete ${provider.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteModal.toggle(true);
                    }}
                  />
                </Hoverable.Item>
                <Button
                  icon={SvgSettings}
                  prominence="tertiary"
                  aria-label={`Edit ${provider.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsOpen(true);
                  }}
                />
              </div>
            }
          />
        </SelectCard>
      </Hoverable.Root>
    </>
  );
}

// ============================================================================
// NewProviderCard — card for the "Add Provider" list
// ============================================================================

interface NewProviderCardProps {
  providerName: string;
  isFirstProvider: boolean;
}

function NewProviderCard({
  providerName,
  isFirstProvider,
}: NewProviderCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { icon, productName, companyName, Modal } = getProvider(providerName);

  return (
    <SelectCard
      state="empty"
      padding="sm"
      rounding="lg"
      onClick={() => setIsOpen(true)}
    >
      <CardLayout.Header
        headerPadding="sm"
        headerChildren={
          <Content
            icon={icon}
            title={productName}
            description={companyName}
            sizePreset="main-ui"
            variant="section"
          />
        }
        topRightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            onClick={(e) => {
              e.stopPropagation();
              setIsOpen(true);
            }}
          >
            Connect
          </Button>
        }
      />
      {isOpen && (
        <Modal shouldMarkAsDefault={isFirstProvider} onOpenChange={setIsOpen} />
      )}
    </SelectCard>
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
  const { icon, productName, companyName, Modal } = getProvider("custom");

  return (
    <SelectCard
      state="empty"
      padding="sm"
      rounding="lg"
      onClick={() => setIsOpen(true)}
    >
      <CardLayout.Header
        headerPadding="sm"
        headerChildren={
          <Content
            icon={icon}
            title={productName}
            description={companyName}
            sizePreset="main-ui"
            variant="section"
          />
        }
        topRightChildren={
          <Button
            rightIcon={SvgArrowExchange}
            prominence="tertiary"
            onClick={(e) => {
              e.stopPropagation();
              setIsOpen(true);
            }}
          >
            Set Up
          </Button>
        }
      />
      {isOpen && (
        <Modal shouldMarkAsDefault={isFirstProvider} onOpenChange={setIsOpen} />
      )}
    </SelectCard>
  );
}

// ============================================================================
// LLMConfigurationPage — main page component
// ============================================================================

export default function LLMConfigurationPage() {
  const { mutate } = useSWRConfig();
  const { llmProviders: existingLlmProviders, defaultText } =
    useAdminLLMProviders();

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
      await refreshLlmProviderCaches(mutate);
      toast.success("Default model updated successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to set default model: ${message}`);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />

      <SettingsLayouts.Body>
        {hasProviders ? (
          <Card border="solid" rounding="lg">
            <InputHorizontal
              title="Default Model"
              description="This model will be used by Onyx by default in your chats."
              center
              withLabel
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
            </InputHorizontal>
          </Card>
        ) : (
          <MessageCard
            variant="info"
            title="Set up an LLM provider to start chatting."
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

            <Divider paddingParallel="fit" paddingPerpendicular="fit" />
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
            {PROVIDER_DISPLAY_ORDER.map((name) => (
              <NewProviderCard
                key={name}
                providerName={name}
                isFirstProvider={isFirstProvider}
              />
            ))}
            <NewCustomProviderCard isFirstProvider={isFirstProvider} />
          </div>
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
