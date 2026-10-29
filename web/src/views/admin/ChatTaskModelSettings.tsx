"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { DropdownLoader } from "@opal/loaders";
import { InputHorizontal, toast, useErrorToast } from "@opal/layouts";
import {
  useAdminLanguageModels,
  useDecisionModel,
} from "@/lib/languageModels/hooks";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { filterModelConfigurations } from "@/lib/languageModels/options";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import { useSettings } from "@/lib/settings/hooks";
import type {
  DefaultModel,
  ModelOptionProvider,
} from "@/lib/languageModels/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  deleteDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  saveDecisionModel,
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
  const [isPending, setIsPending] = useState(false);
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
        // Unset, a task runs on the chat's own model.
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

// One provider list with each provider's chat models and decision models;
// a model that is both appears once.
function mergeProviders<T extends ModelOptionProvider>(
  chatProviders: T[],
  decisionProviders: T[]
): T[] {
  const merged = new Map<number, T>();
  for (const provider of [...chatProviders, ...decisionProviders]) {
    const existing = merged.get(provider.id);
    if (!existing) {
      merged.set(provider.id, provider);
      continue;
    }
    const known = new Set(existing.model_configurations.map((m) => m.id));
    merged.set(provider.id, {
      ...existing,
      model_configurations: [
        ...existing.model_configurations,
        ...provider.model_configurations.filter((m) => !known.has(m.id)),
      ],
    });
  }
  return [...merged.values()];
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
 * how much context to add. A decision model takes the decision-model path;
 * a language model keeps LLM selection. A model that is both counts as a
 * decision model.
 */
export function SearchDecisionModelSetting() {
  const t = useTranslations("admin.chatPreferences");
  const settings = useSettings();
  const [isPending, setIsPending] = useState(false);
  const { llmProviders, defaultSearchSelection, modelPaging, refetch, error } =
    useAdminLanguageModels();
  const decision = useDecisionModel();
  const loadError = error ?? decision.error;

  const decisionModelIds = useMemo(
    () =>
      new Set(
        (decision.providers ?? []).flatMap((provider) =>
          provider.model_configurations.map((config) => config.id)
        )
      ),
    [decision.providers]
  );
  const value =
    modelConfigurationId(decision.providers, decision.model) ??
    modelConfigurationId(llmProviders, defaultSearchSelection);
  const providers = useMemo(
    () =>
      mergeProviders(
        llmProviders
          ? filterModelConfigurations(llmProviders, { keep: value })
          : [],
        decision.providers ?? []
      ),
    [llmProviders, decision.providers, value]
  );

  async function handleChange(modelId: number | null) {
    if (isPending) return;
    const provider =
      modelId === null
        ? null
        : findProviderOwningModelConfig(providers, modelId);
    const model = provider?.model_configurations.find(
      (configuration) => configuration.id === modelId
    );
    if (modelId !== null && (!provider || !model)) {
      toast.error(t("toasts.providerResolveFailed"));
      return;
    }
    const selection =
      provider && model
        ? { provider_id: provider.id, model_name: model.name }
        : null;
    setIsPending(true);
    try {
      // Exactly one default stays set: it picks the search path.
      if (selection && modelId !== null && decisionModelIds.has(modelId)) {
        await saveDecisionModel(selection);
        if (defaultSearchSelection) await deleteDefaultSearchSelectionModel();
      } else {
        if (selection) {
          await setDefaultSearchSelectionModel(
            selection.provider_id,
            selection.model_name
          );
        } else if (defaultSearchSelection) {
          await deleteDefaultSearchSelectionModel();
        }
        if (decision.model) await saveDecisionModel(null);
      }
      await Promise.all([refetch(), decision.refetch()]);
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("toasts.searchDecisionUpdateFailed")
      );
    } finally {
      setIsPending(false);
    }
  }

  useErrorToast(loadError, {
    id: "search-decision-model-load-failed",
    message: t("taskModels.loadFailed"),
    retry: {
      label: t("taskModels.retry.label"),
      onRetry: () => void Promise.all([refetch(), decision.refetch()]),
    },
  });

  let control: React.ReactNode;
  if ((!llmProviders || !decision.providers) && !loadError) {
    control = <DropdownLoader />;
  } else if (llmProviders?.length === 0 && decision.providers?.length === 0) {
    control = (
      <Button href={ADMIN_ROUTES.LLM_MODELS.path} prominence="secondary">
        {t("taskModels.addProvider.label")}
      </Button>
    );
  } else {
    control = (
      <SimpleModelSelector
        nullable
        includeDecisionOnly
        globalDefault={{ label: t("taskModels.chatDefault.label") }}
        providers={providers}
        value={value}
        disabled={isPending || !!loadError}
        isError={loadError ? true : undefined}
        grouped={!settings.hide_provider_grouping}
        modelPaging={modelPaging}
        onChange={(modelId) => void handleChange(modelId)}
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
