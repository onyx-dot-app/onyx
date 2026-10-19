"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, MessageCard, OnyxLoader } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { filterModelConfigurations } from "@/lib/languageModels/options";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type { DefaultModel } from "@/lib/languageModels/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import DecisionModelSetting from "@/views/admin/DecisionModelSetting";
import {
  deleteDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  setDefaultChatNamingModel,
  setDefaultSearchSelectionModel,
} from "@/lib/languageModels/svc";

export default function ChatTaskModelSettings() {
  const t = useTranslations("admin.chatPreferences");
  const settings = useSettings();
  const [isChatNamingPending, setIsChatNamingPending] = useState(false);
  const [isSearchSelectionPending, setIsSearchSelectionPending] =
    useState(false);
  const {
    llmProviders,
    defaultChatNaming,
    defaultSearchSelection,
    modelPaging,
    refetch,
    error,
  } = useAdminLanguageModels();

  const chatNamingModelConfigId = useMemo(() => {
    if (!defaultChatNaming || !llmProviders) return null;
    const provider = llmProviders.find(
      (p) => p.id === defaultChatNaming.provider_id
    );
    return (
      provider?.model_configurations.find(
        (m) => m.name === defaultChatNaming.model_name
      )?.id ?? null
    );
  }, [defaultChatNaming, llmProviders]);

  const searchSelectionModelConfigId = useMemo(() => {
    if (!defaultSearchSelection || !llmProviders) return null;
    const provider = llmProviders.find(
      (p) => p.id === defaultSearchSelection.provider_id
    );
    return (
      provider?.model_configurations.find(
        (m) => m.name === defaultSearchSelection.model_name
      )?.id ?? null
    );
  }, [defaultSearchSelection, llmProviders]);

  async function handleChatNamingChange(model: DefaultModel | null) {
    if (isChatNamingPending) return;
    setIsChatNamingPending(true);
    try {
      if (model) {
        await setDefaultChatNamingModel(model.provider_id, model.model_name);
      } else {
        await deleteDefaultChatNamingModel();
      }
      await refetch();
      toast.success(
        t(model ? "toasts.chatNamingUpdated" : "toasts.chatNamingReset")
      );
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t(
              model
                ? "toasts.chatNamingUpdateFailed"
                : "toasts.chatNamingResetFailed"
            )
      );
    } finally {
      setIsChatNamingPending(false);
    }
  }

  async function handleSearchSelectionChange(model: DefaultModel | null) {
    if (isSearchSelectionPending) return;
    setIsSearchSelectionPending(true);
    try {
      if (model) {
        await setDefaultSearchSelectionModel(
          model.provider_id,
          model.model_name
        );
      } else {
        await deleteDefaultSearchSelectionModel();
      }
      await refetch();
      toast.success(
        t(
          model
            ? "toasts.searchSelectionUpdated"
            : "toasts.searchSelectionReset"
        )
      );
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t(
              model
                ? "toasts.searchSelectionUpdateFailed"
                : "toasts.searchSelectionResetFailed"
            )
      );
    } finally {
      setIsSearchSelectionPending(false);
    }
  }

  if (error) {
    return (
      <MessageCard
        variant="error"
        title={t("taskModels.loadFailed")}
        rightChildren={
          <Button prominence="secondary" onClick={() => void refetch()}>
            {t("taskModels.retry.label")}
          </Button>
        }
      />
    );
  }

  if (!llmProviders) {
    return (
      <Section height="auto">
        <OnyxLoader size={24} />
      </Section>
    );
  }

  if (llmProviders.length === 0) {
    return (
      <MessageCard
        title={t("taskModels.noProviders.title")}
        rightChildren={
          <Button href={ADMIN_ROUTES.LLM_MODELS.path} prominence="secondary">
            {t("taskModels.addProvider.label")}
          </Button>
        }
      />
    );
  }

  return (
    <Card border="solid" rounding={4}>
      <Section alignItems="stretch">
        <InputHorizontal
          title={t("chatNaming.title")}
          description={t("chatNaming.description")}
          suffix="optional"
        >
          <Section
            role="group"
            aria-label={t("chatNaming.title")}
            flexDirection="row"
            width="fit"
            height="auto"
            gap={2}
          >
            {defaultChatNaming !== null && (
              <Button
                prominence="tertiary"
                size="sm"
                disabled={isChatNamingPending}
                onClick={() => void handleChatNamingChange(null)}
              >
                {t("chatNaming.resetButton.label")}
              </Button>
            )}
            <SimpleModelSelector
              placeholder={t("chatNaming.sessionModel.label")}
              providers={filterModelConfigurations(llmProviders, {
                visibleOnly: false,
                keep: chatNamingModelConfigId,
              })}
              value={chatNamingModelConfigId}
              disabled={isChatNamingPending}
              grouped={!settings.hide_provider_grouping}
              modelPaging={modelPaging}
              onChange={(modelConfigurationId) => {
                const provider = findProviderOwningModelConfig(
                  llmProviders,
                  modelConfigurationId
                );
                const model = provider?.model_configurations.find(
                  (configuration) => configuration.id === modelConfigurationId
                );
                if (!provider || !model) {
                  toast.error(t("toasts.providerResolveFailed"));
                  return;
                }
                void handleChatNamingChange({
                  provider_id: provider.id,
                  model_name: model.name,
                });
              }}
            />
          </Section>
        </InputHorizontal>
        <InputHorizontal
          title={t("searchSelectionModel.title")}
          description={t("searchSelectionModel.description")}
          suffix="optional"
        >
          <Section
            role="group"
            aria-label={t("searchSelectionModel.title")}
            flexDirection="row"
            width="fit"
            height="auto"
            gap={2}
          >
            {defaultSearchSelection !== null && (
              <Button
                prominence="tertiary"
                size="sm"
                disabled={isSearchSelectionPending}
                onClick={() => void handleSearchSelectionChange(null)}
              >
                {t("searchSelectionModel.resetButton.label")}
              </Button>
            )}
            <SimpleModelSelector
              placeholder={t("searchSelectionModel.sessionModel.label")}
              providers={filterModelConfigurations(llmProviders, {
                visibleOnly: false,
                keep: searchSelectionModelConfigId,
              })}
              value={searchSelectionModelConfigId}
              disabled={isSearchSelectionPending}
              grouped={!settings.hide_provider_grouping}
              modelPaging={modelPaging}
              onChange={(modelConfigurationId) => {
                const provider = findProviderOwningModelConfig(
                  llmProviders,
                  modelConfigurationId
                );
                const model = provider?.model_configurations.find(
                  (configuration) => configuration.id === modelConfigurationId
                );
                if (!provider || !model) {
                  toast.error(t("toasts.providerResolveFailed"));
                  return;
                }
                void handleSearchSelectionChange({
                  provider_id: provider.id,
                  model_name: model.name,
                });
              }}
            />
          </Section>
        </InputHorizontal>
        <DecisionModelSetting />
      </Section>
    </Card>
  );
}
