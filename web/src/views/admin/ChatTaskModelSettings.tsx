"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { DropdownLoader } from "@opal/loaders";
import { InputHorizontal, toast, useErrorToast } from "@opal/layouts";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { filterModelConfigurations } from "@/lib/languageModels/options";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type { DefaultModel } from "@/lib/languageModels/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  deleteDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  setDefaultChatNamingModel,
  setDefaultSearchSelectionModel,
} from "@/lib/languageModels/svc";

// The two background tasks with their own model. Each row reads and writes one
// designation; the Global Default row leaves it unset.
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

const CLEAR_TASK_MODEL = {
  chatNaming: deleteDefaultChatNamingModel,
  searchSelection: deleteDefaultSearchSelectionModel,
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

  async function handleChange(model: DefaultModel | null) {
    if (isPending) return;
    setIsPending(true);
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
    } finally {
      setIsPending(false);
    }
  }

  // Both rows share the listing, so they share one toast.
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
  } else if (llmProviders?.length === 0) {
    control = (
      <Button href={ADMIN_ROUTES.LLM_MODELS.path} prominence="secondary">
        {t("taskModels.addProvider.label")}
      </Button>
    );
  } else {
    control = (
      <SimpleModelSelector
        nullable
        // Unset, a task runs on the chat's own model. In the Search UI,
        // search selection falls back to the workspace default instead; the
        // one label covers the common case.
        globalDefault={{ label: t("taskModels.chatDefault.label") }}
        providers={
          llmProviders
            ? filterModelConfigurations(llmProviders, { keep: modelConfigId })
            : []
        }
        value={modelConfigId}
        disabled={isPending || !!error}
        isError={error ? true : undefined}
        grouped={!settings.hide_provider_grouping}
        modelPaging={modelPaging}
        onChange={(modelConfigurationId) => {
          if (modelConfigurationId === null) {
            void handleChange(null);
            return;
          }
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

/** Model that selects and checks retrieved documents. */
export function SearchSelectionModelSetting() {
  return <TaskModelSetting task="searchSelection" />;
}
