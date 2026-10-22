"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  MessageCard,
  OnyxLoader,
  SelectCard,
  Text,
  useCreateModal,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import {
  CardGrid,
  Content,
  ContentAction,
  Section,
  SettingsLayouts,
  ConfirmationModalLayout,
  toast,
} from "@opal/layouts";
import { SvgArrowExchange, SvgSettings, SvgTrash } from "@opal/icons";
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
import DecisionProviderModal from "@/sections/modals/languageModels/DecisionProviderModal";
import ZoomDecisionModal from "@/sections/modals/languageModels/ZoomDecisionModal";

interface DecisionProviderCardProps {
  providerName: string;
  provider?: LLMProviderView;
}

/** One provider, styled like the Language Models provider cards. */
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
  const providerId = provider?.id ?? null;
  const { llmProvider: fullProvider, error } = useAdminLanguageModel(
    open ? providerId : null
  );
  const { icon, companyName, productName, decisionOnly } =
    getProvider(providerName);
  const isSelected =
    providerId !== null && providerId === selectedModel?.provider_id;
  const displayName = provider?.name || companyName;
  const modelNames = provider?.model_configurations
    .map((model) => model.effectiveDisplayName)
    .join(", ");

  // A provider that fails to load closes its editor and says so, as on the
  // Language Models page.
  useEffect(() => {
    if (!error || providerId === null) return;
    toast.error(
      tLlm("toasts.providerLoadFailed", {
        message:
          error instanceof Error ? error.message : tLlm("toasts.unknownError"),
      })
    );
    setOpen(false);
    // Drop the cached failure so the next open fetches again.
    void mutate(SWR_KEYS.adminLlmProvider(providerId), undefined, {
      revalidate: false,
    });
  }, [error, providerId, mutate, tLlm]);

  async function remove() {
    if (!provider || isSelected || removing) return;
    setRemoving(true);
    try {
      await deleteLlmProvider(provider.id);
      await refreshLlmProviderCaches(mutate);
      deleteModal.toggle(false);
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
      {open &&
        (!provider || fullProvider) &&
        (providerName === "zoom_ai" ? (
          <ZoomDecisionModal
            existingLlmProvider={fullProvider ?? undefined}
            onOpenChange={setOpen}
            onSuccess={() => refreshLlmProviderCaches(mutate)}
          />
        ) : (
          <DecisionProviderModal
            providerName={providerName}
            existingLlmProvider={fullProvider ?? undefined}
            onOpenChange={setOpen}
            onSuccess={() => refreshLlmProviderCaches(mutate)}
          />
        ))}
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
      <Hoverable.Root
        group="DecisionProviderCard"
        interaction={deleteModal.isOpen ? "hover" : "rest"}
      >
        <SelectCard
          state={provider ? "filled" : "empty"}
          padding={2}
          rounding={4}
          aria-label={displayName}
          onClick={() => setOpen(true)}
        >
          <ContentAction
            icon={icon}
            title={displayName}
            description={modelNames || productName}
            titleMaxLines={1}
            descriptionMaxLines={1}
            sizePreset="main-ui"
            variant="section"
            padding={2}
            rightChildren={
              provider ? (
                <Section flexDirection="row" width="fit" height="fit" gap={0}>
                  {decisionOnly && (
                    <Hoverable.Item
                      group="DecisionProviderCard"
                      variant="appear-on-hover"
                    >
                      <Button
                        icon={SvgTrash}
                        prominence="tertiary"
                        aria-label={tLlm(
                          "providerCard.deleteButton.ariaLabel",
                          {
                            provider: displayName,
                          }
                        )}
                        onClick={(event) => {
                          event.stopPropagation();
                          deleteModal.toggle(true);
                        }}
                      />
                    </Hoverable.Item>
                  )}
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    aria-label={tLlm("providerCard.editButton.ariaLabel", {
                      provider: displayName,
                    })}
                    onClick={(event) => {
                      event.stopPropagation();
                      setOpen(true);
                    }}
                  />
                </Section>
              ) : (
                <Button
                  rightIcon={SvgArrowExchange}
                  prominence="tertiary"
                  onClick={(event) => {
                    event.stopPropagation();
                    setOpen(true);
                  }}
                >
                  {t("providers.connect")}
                </Button>
              )
            }
          />
        </SelectCard>
      </Hoverable.Root>
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
  } = useAdminLanguageModels({ revalidateIfStale: true });

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
        <CardGrid>
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
        </CardGrid>
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
