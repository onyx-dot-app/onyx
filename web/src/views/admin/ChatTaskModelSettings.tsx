"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { DropdownLoader } from "@opal/loaders";
import { InputHorizontal, toast, useErrorToast } from "@opal/layouts";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { filterModelConfigurations } from "@/lib/languageModels/options";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type {
  DefaultModel,
  ModelOptionProvider,
} from "@/lib/languageModels/types";
import {
  deleteDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  setDefaultChatNamingModel,
  setDefaultSearchSelectionModel,
} from "@/lib/languageModels/svc";

// Background tasks with their own language model. Each row reads and writes
// one designation; the Global Default row leaves it unset.
type TaskModel = "chatNaming";

const TASK_COPY = {
  chatNaming: {
    section: "chatNaming",
    updateFailed: "toasts.chatNamingUpdateFailed",
  },
} as const;

const SAVE_TASK_MODEL = {
  chatNaming: setDefaultChatNamingModel,
} as const;

const CLEAR_TASK_MODEL = {
  chatNaming: deleteDefaultChatNamingModel,
} as const;

interface TaskModelSettingProps {
  task: TaskModel;
}

function TaskModelSetting({ task }: TaskModelSettingProps) {
  const t = useTranslations("admin.chatPreferences");
  const settings = useSettings();
  const { llmProviders, defaultChatNaming, modelPaging, refetch, error } =
    useAdminLanguageModels();
  const copy = TASK_COPY[task];
  const current = defaultChatNaming;

  const modelConfigId = useMemo(() => {
    if (!current || !llmProviders) return null;
    const provider = llmProviders.find((p) => p.id === current.provider_id);
    return (
      provider?.model_configurations.find((m) => m.name === current.model_name)
        ?.id ?? null
    );
  }, [current, llmProviders]);

  async function handleChange(model: DefaultModel | null) {
    try {
      if (model) {
        await SAVE_TASK_MODEL[task](model.provider_id, model.model_name);
      } else {
        await CLEAR_TASK_MODEL[task]();
      }
      await refetch();
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t(copy.updateFailed)
      );
    }
  }

  useErrorToast(error, {
    id: "task-models-load-failed",
    message: t("taskModels.loadFailed"),
    retry: {
      label: t("taskModels.retry.label"),
      onRetry: () => void refetch(),
    },
  });

  let control: React.ReactNode;
  if (!llmProviders && !error) {
    control = <DropdownLoader />;
  } else {
    control = (
      <SimpleModelSelector
        nullable
        // Unset, a task runs on the chat's own model.
        globalDefault={{ label: t("taskModels.chatDefault.label") }}
        providers={
          llmProviders
            ? filterModelConfigurations(llmProviders, { keep: modelConfigId })
            : []
        }
        value={modelConfigId}
        disabled={!!error}
        isError={error ? true : undefined}
        grouped={!settings.hide_provider_grouping}
        modelPaging={modelPaging}
        onChange={(modelConfigurationId) => {
          if (modelConfigurationId === null) return handleChange(null);
          if (!llmProviders) return;
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
          return handleChange({
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
      // The title opens the select, like the page's other select rows.
      withLabel
      fillInput
    >
      {control}
    </InputHorizontal>
  );
}

/** Model that names chat sessions. */
export function ChatNamingModelSetting() {
  return <TaskModelSetting task="chatNaming" />;
}

function modelConfigurationId(
  providers: ModelOptionProvider[] | undefined,
  model: DefaultModel | null
): number | null {
  if (!model || !providers) return null;
  return (
    providers
      .find((provider) => provider.id === model.provider_id)
      ?.model_configurations.find((config) => config.name === model.model_name)
      ?.id ?? null
  );
}

/**
 * Model for search's evidence decisions: which retrieved sections to keep and
 * how much context to add. Unset, search uses the chat's own model.
 */
export function SearchDecisionModelSetting() {
  const t = useTranslations("admin.chatPreferences");
  const settings = useSettings();
  const { llmProviders, defaultSearchSelection, modelPaging, refetch, error } =
    useAdminLanguageModels();

  const value = modelConfigurationId(llmProviders, defaultSearchSelection);
  const languageProviders = useMemo(
    () =>
      llmProviders
        ? filterModelConfigurations(llmProviders, { keep: value })
        : [],
    [llmProviders, value]
  );
  async function handleChange(modelId: number | null) {
    const provider =
      modelId === null
        ? null
        : findProviderOwningModelConfig(languageProviders, modelId);
    const model = provider?.model_configurations.find(
      (configuration) => configuration.id === modelId
    );
    if (modelId !== null && (!provider || !model)) {
      toast.error(t("toasts.providerResolveFailed"));
      return;
    }
    try {
      if (provider && model) {
        await setDefaultSearchSelectionModel(provider.id, model.name);
      } else if (defaultSearchSelection) {
        await deleteDefaultSearchSelectionModel();
      }
      await refetch();
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("toasts.searchDecisionUpdateFailed")
      );
    }
  }

  useErrorToast(error, {
    id: "search-decision-model-load-failed",
    message: t("taskModels.loadFailed"),
    retry: {
      label: t("taskModels.retry.label"),
      onRetry: () => void refetch(),
    },
  });

  let control: React.ReactNode;
  if (!llmProviders && !error) {
    control = <DropdownLoader />;
  } else {
    control = (
      <SimpleModelSelector
        nullable
        globalDefault={{ label: t("taskModels.chatDefault.label") }}
        providers={languageProviders}
        value={value}
        disabled={!!error}
        isError={error ? true : undefined}
        grouped={!settings.hide_provider_grouping}
        modelPaging={modelPaging}
        onChange={(modelId) => handleChange(modelId)}
      />
    );
  }

  return (
    <InputHorizontal
      title={t("searchDecisionModel.title")}
      description={t("searchDecisionModel.description")}
      withLabel
      fillInput
    >
      {control}
    </InputHorizontal>
  );
}
