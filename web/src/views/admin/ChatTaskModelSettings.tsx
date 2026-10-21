"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, OnyxLoader, Text } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { filterModelConfigurations } from "@/lib/languageModels/options";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type { DefaultModel } from "@/lib/languageModels/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  setDefaultChatNamingModel,
  setDefaultSearchSelectionModel,
} from "@/lib/languageModels/svc";

// The two background tasks with their own model. Each row reads and writes one
// designation; unset, the task uses the chat's model.
type TaskModel = "chatNaming" | "searchSelection";

const TASK_COPY = {
  chatNaming: {
    section: "chatNaming",
    updateFailed: "toasts.chatNamingUpdateFailed",
  },
  searchSelection: {
    section: "searchSelectionModel",
    updateFailed: "toasts.searchSelectionUpdateFailed",
  },
} as const;

const SAVE_TASK_MODEL = {
  chatNaming: setDefaultChatNamingModel,
  searchSelection: setDefaultSearchSelectionModel,
} as const;

interface TaskModelSettingProps {
  task: TaskModel;
}

function TaskModelSetting({ task }: TaskModelSettingProps) {
  const t = useTranslations("admin.chatPreferences");
  const settings = useSettings();
  const [isPending, setIsPending] = useState(false);
  const {
    llmProviders,
    defaultChatNaming,
    defaultSearchSelection,
    modelPaging,
    refetch,
    error,
  } = useAdminLanguageModels();
  const copy = TASK_COPY[task];
  const current =
    task === "chatNaming" ? defaultChatNaming : defaultSearchSelection;

  const modelConfigId = useMemo(() => {
    if (!current || !llmProviders) return null;
    const provider = llmProviders.find((p) => p.id === current.provider_id);
    return (
      provider?.model_configurations.find((m) => m.name === current.model_name)
        ?.id ?? null
    );
  }, [current, llmProviders]);

  async function handleChange(model: DefaultModel) {
    if (isPending) return;
    setIsPending(true);
    try {
      await SAVE_TASK_MODEL[task](model.provider_id, model.model_name);
      await refetch();
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t(copy.updateFailed)
      );
    } finally {
      setIsPending(false);
    }
  }

  let control: React.ReactNode;
  if (error) {
    control = (
      <Section flexDirection="row" alignItems="center" width="fit" gap={2}>
        <Text font="secondary-body" color="text-03">
          {t("taskModels.loadFailed")}
        </Text>
        <Button prominence="secondary" onClick={() => void refetch()}>
          {t("taskModels.retry.label")}
        </Button>
      </Section>
    );
  } else if (!llmProviders) {
    control = <OnyxLoader size={24} />;
  } else if (llmProviders.length === 0) {
    control = (
      <Button href={ADMIN_ROUTES.LLM_MODELS.path} prominence="secondary">
        {t("taskModels.addProvider.label")}
      </Button>
    );
  } else {
    control = (
      <SimpleModelSelector
        placeholder={t(`${copy.section}.sessionModel.label`)}
        providers={filterModelConfigurations(llmProviders, {
          visibleOnly: false,
          keep: modelConfigId,
        })}
        value={modelConfigId}
        disabled={isPending}
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
          void handleChange({
            provider_id: provider.id,
            model_name: model.name,
          });
        }}
      />
    );
  }

  return (
    <InputHorizontal
      title={t(`${copy.section}.title`)}
      description={t(`${copy.section}.description`)}
      suffix="optional"
      fillInput
    >
      {control}
    </InputHorizontal>
  );
}

/** Model that names chat sessions; unset, each session's model names it. */
export function ChatNamingModelSetting() {
  return <TaskModelSetting task="chatNaming" />;
}

/** Model that selects retrieved documents; unset, each chat's model does. */
export function SearchSelectionModelSetting() {
  return <TaskModelSetting task="searchSelection" />;
}
