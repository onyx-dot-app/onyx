"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  MessageCard,
  OnyxLoader,
  Text,
  useCreateModal,
} from "@opal/components";
import {
  Content,
  ContentAction,
  Section,
  SettingsLayouts,
  ConfirmationModalLayout,
  toast,
} from "@opal/layouts";
import { SvgTrash } from "@opal/icons";
import { markdown } from "@opal/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  useAdminLanguageModel,
  useAdminLanguageModels,
  useDecisionModel,
} from "@/lib/languageModels/hooks";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { getProvider } from "@/lib/languageModels/utils";
import type { LLMProviderView } from "@/lib/languageModels/types";
import DecisionModelSetting from "@/views/admin/DecisionModelSetting";
import { SWR_KEYS } from "@/lib/swr-keys";
import { deleteLlmProvider } from "@/lib/languageModels/svc";

interface DecisionProviderCardProps {
  providerName: string;
  provider?: LLMProviderView;
}

function DecisionProviderCard({
  providerName,
  provider,
}: DecisionProviderCardProps) {
  const t = useTranslations("admin.decisionModels");
  const tLlm = useTranslations("admin.languageModels");
  const { mutate } = useSWRConfig();
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState(false);
  const deleteModal = useCreateModal();
  const { model: selectedModel } = useDecisionModel();
  const { llmProvider: fullProvider, error } = useAdminLanguageModel(
    open && provider ? provider.id : null
  );
  const { icon, companyName, productName, Modal, decisionOnly } =
    getProvider(providerName);
  const isSelected = provider?.id === selectedModel?.provider_id;
  const displayName = provider?.name || companyName;

  async function remove() {
    if (!provider || isSelected || removing) return;
    setRemoving(true);
    try {
      await deleteLlmProvider(provider.id);
      await refreshLlmProviderCaches(mutate);
      deleteModal.toggle(false);
      toast.success(tLlm("toasts.providerDeleted"));
    } catch (error) {
      toast.error(
        tLlm("toasts.providerDeleteFailed", {
          message:
            error instanceof Error
              ? error.message
              : tLlm("toasts.unknownError"),
        })
      );
    } finally {
      setRemoving(false);
    }
  }

  return (
    <>
      <Card
        border="solid"
        data-testid={`decision-provider-${providerName}-${provider?.id ?? "new"}`}
      >
        <Section gap={3} alignItems="stretch">
          <ContentAction
            icon={icon}
            title={provider?.name || companyName}
            description={productName}
            sizePreset="main-content"
            variant="section"
            rightChildren={
              <Section flexDirection="row" width="fit" gap={2}>
                {provider && decisionOnly && (
                  <Button
                    prominence="tertiary"
                    onClick={() => deleteModal.toggle(true)}
                  >
                    {tLlm("deleteModal.submit.label")}
                  </Button>
                )}
                <Button prominence="secondary" onClick={() => setOpen(true)}>
                  {t(provider ? "providers.edit" : "providers.connect")}
                </Button>
              </Section>
            }
          />
          {provider &&
            provider.model_configurations.map((model) => (
              <Text key={model.name} font="secondary-body" color="text-03">
                {model.effectiveDisplayName}
              </Text>
            ))}
          {open && provider && !fullProvider && !error && (
            <OnyxLoader size={24} />
          )}
          {open && error && (
            <MessageCard
              variant="error"
              title={t("loadFailed")}
              rightChildren={
                <Button
                  prominence="secondary"
                  onClick={() =>
                    provider &&
                    void mutate(SWR_KEYS.adminLlmProvider(provider.id))
                  }
                >
                  {t("retry")}
                </Button>
              }
            />
          )}
          {open && (!provider || fullProvider) && (
            <Modal
              existingLlmProvider={fullProvider ?? undefined}
              modelScope="decision"
              shouldMarkAsDefault={false}
              onOpenChange={setOpen}
              onSuccess={() => refreshLlmProviderCaches(mutate)}
            />
          )}
        </Section>
      </Card>
      {provider && deleteModal.isOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={markdown(tLlm("deleteModal.title", { provider: displayName }))}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              variant="danger"
              disabled={isSelected || removing}
              onClick={() => void remove()}
            >
              {tLlm("deleteModal.submit.label")}
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03">
            {isSelected
              ? t("providers.clearBeforeRemoval")
              : markdown(
                  tLlm("deleteModal.description", { provider: displayName })
                )}
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}

function DecisionModelsContent() {
  const t = useTranslations("admin.decisionModels");
  const { providers, supportedProviders, error, refetch } = useDecisionModel();
  const {
    llmProviders,
    error: providersError,
    refetch: refetchProviders,
  } = useAdminLanguageModels();

  if (error || providersError) {
    return (
      <MessageCard
        variant="error"
        title={t("loadFailed")}
        rightChildren={
          <Button
            prominence="secondary"
            onClick={() => void Promise.all([refetch(), refetchProviders()])}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  }
  if (!providers || !llmProviders) return <OnyxLoader size={24} />;

  return (
    <>
      <Card border="solid">
        <DecisionModelSetting />
      </Card>
      <Section gap={3} alignItems="stretch">
        <Content
          title={t("providers.title")}
          description={t("providers.description")}
          sizePreset="main-content"
          variant="section"
        />
        {supportedProviders.map((providerName) => {
          const connected = llmProviders.filter(
            (provider) => provider.provider === providerName
          );
          return connected.length > 0 ? (
            connected.map((provider) => (
              <DecisionProviderCard
                key={provider.id}
                providerName={providerName}
                provider={{
                  ...provider,
                  model_configurations:
                    providers.find((entry) => entry.id === provider.id)
                      ?.model_configurations ?? [],
                }}
              />
            ))
          ) : (
            <DecisionProviderCard
              key={providerName}
              providerName={providerName}
            />
          );
        })}
      </Section>
    </>
  );
}

export default function DecisionModelsPage() {
  const t = useTranslations("admin.decisionModels");
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={ADMIN_ROUTES.DECISION_MODELS.icon}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <DecisionModelsContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
