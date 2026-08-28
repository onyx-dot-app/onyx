"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Formik } from "formik";
import { markdown } from "@opal/utils";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { PageLoader } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, IllustrationContent, toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import {
  Button,
  Card,
  Divider,
  InputTypeIn,
  LinkButton,
  MessageCard,
  SelectCard,
  Spacer,
  Switch,
  Tabs,
  Text,
} from "@opal/components";
import {
  SvgArrowExchange,
  SvgCheckSquare,
  SvgClock,
  SvgCloud,
  SvgEmpty,
  SvgExternalLink,
  SvgFold,
  SvgPlusCircle,
  SvgRevert,
  SvgServer,
  SvgSettings,
  SvgSlowTime,
  SvgUnplug,
  SvgVector,
} from "@opal/icons";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import {
  EmbeddingProviderName,
  SwitchoverType,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingModelRequest,
  type EmbeddingModelSelection,
  type EmbeddingModelState,
  type EmbeddingProvider,
} from "@/lib/indexing/types";
import {
  CLOUD_BASED_PROVIDERS,
  CUSTOM_PROVIDER,
  SELF_HOSTED_PROVIDERS,
  findProvider,
  findRegistryModel,
  isCloudBased,
  MAX_IMAGE_SIZE_OPTIONS,
  resolveProviderName,
} from "@/lib/indexing";
import {
  isSameModelSelection,
  resolveModelForApply,
  savedModelSelection,
} from "@/lib/indexing/utils";
import {
  saveAdminSettings,
  cancelNewEmbedding,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
  updateInferenceSettings,
} from "@/lib/indexing/svc";
import { useCreateModal } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { ConfirmationModalLayout } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { Settings, toSettings } from "@/lib/settings/types";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useReindexProgress,
  useSecondarySearchSettings,
} from "@/lib/indexing/hooks";
import { useLlmDefaults } from "@/lib/languageModels/hooks";
import useFilter from "@/hooks/useFilter";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import type { RichStr } from "@opal/types";
import { ProviderCredentialsModal } from "@/views/admin/IndexSettingsPage/modals";
import ReindexProgressBanner from "@/views/admin/IndexSettingsPage/ReindexProgressBanner";
import { parseErrorDetail } from "@/lib/fetcher";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MODEL_TAB_CLOUD = "cloud-based";
const MODEL_TAB_SELF = "self-hosted";
// Developer-facing log label only; the user-visible copy comes from `t`.
const CONTEXTUAL_MODEL_UPDATE_LOG = "Failed to update Contextual Retrieval LLM";

/**
 * Wrapper that disables its children when either:
 * 1. The app is running on Onyx Cloud (`NEXT_PUBLIC_CLOUD_ENABLED`), or
 * 2. A local `disabled` condition is true (e.g. a parent toggle is off).
 */
interface CloudDisabledProps {
  disabled?: boolean;
  tooltip?: string | RichStr;
  children: React.ReactNode;
}
function CloudDisabled({
  disabled = false,
  tooltip: tooltipProp,
  children,
}: CloudDisabledProps) {
  const t = useTranslations("admin.indexSettings");
  const isDisabled = NEXT_PUBLIC_CLOUD_ENABLED || disabled;
  const tooltip = NEXT_PUBLIC_CLOUD_ENABLED
    ? t("cloudDisabled.tooltip")
    : tooltipProp;

  return (
    <Disabled disabled={isDisabled} tooltip={tooltip} tooltipSide="right">
      {children}
    </Disabled>
  );
}

interface EmbeddingProviderInfoProps {
  providerName: EmbeddingProviderName;
}

function EmbeddingProviderInfo({ providerName }: EmbeddingProviderInfoProps) {
  const t = useTranslations("admin.indexSettings");

  if (!isCloudBased(providerName)) {
    return (
      <Content
        icon={SvgServer}
        title={t("providerInfo.selfHosted.title")}
        sizePreset="secondary"
        variant="body"
        color="muted"
        width="fit"
      />
    );
  }

  const provider = findProvider(providerName);

  return (
    <>
      <Content
        icon={SvgCloud}
        title={t("providerInfo.cloudProvider.title")}
        sizePreset="secondary"
        variant="body"
        color="muted"
        width="fit"
      />
      {provider.costslink && (
        <LinkButton href={provider.costslink} target="_blank">
          {t("providerInfo.pricingLink.label")}
        </LinkButton>
      )}
      {provider.docsLink && (
        <LinkButton href={provider.docsLink} target="_blank">
          {t("providerInfo.docsLink.label")}
        </LinkButton>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Embedding model picker components
// ---------------------------------------------------------------------------

interface ProviderGroupProps {
  provider: EmbeddingProvider;
  currentModelName?: string;
  selectedModelName?: string;
  isCloud?: boolean;
  existingCredentials?: ConfiguredEmbeddingProvider;
  /**
   * Camel-cased spec of the active embedding model when it belongs to THIS
   * provider — passed straight through to `ProviderCredentialsModal` so
   * `LiteLLMProviderModal` can preload its model-spec fields on edit.
   */
  existingModel?: EmbeddingModel;
  /**
   * `customModel` is set only for providers with no pre-registered models
   * (LiteLLM / Azure), where the user defines the spec in the connect modal.
   */
  onSelectModel: (
    modelName: string,
    customModel?: EmbeddingModelRequest
  ) => void;
  onDeselectModel: () => void;
}

function ProviderGroup({
  provider,
  currentModelName,
  selectedModelName,
  isCloud = false,
  existingCredentials,
  existingModel,
  onSelectModel,
  onDeselectModel,
}: ProviderGroupProps) {
  const t = useTranslations("admin.indexSettings");
  const models = provider.embeddingModels;
  const isConfigured = isCloud ? !!existingCredentials : true;
  const disconnectModal = useCreateModal();
  const connectModal = useCreateModal();
  const editCredentialsModal = useCreateModal();
  const providerCreationModal = useCreateModal();
  const [pendingConnectModel, setPendingConnectModel] =
    useState<EmbeddingModel | null>(null);
  const providerGroupContainsCurrentModelName = models.some(
    (m) => m.modelName === currentModelName
  );

  const handleDisconnect = useCallback(async () => {
    if (!isCloud) return;
    try {
      await disconnectEmbeddingProvider(provider.providerName);
      toast.success(
        t("providerGroup.disconnect.successToast", {
          provider: provider.displayName,
        })
      );
      await mutate(SWR_KEYS.embeddingProviders);
      onDeselectModel();
      disconnectModal.toggle(false);
    } catch {
      toast.error(
        t("providerGroup.disconnect.errorToast", {
          provider: provider.displayName,
        })
      );
    }
  }, [
    isCloud,
    provider.providerName,
    provider.displayName,
    onDeselectModel,
    disconnectModal,
    t,
  ]);

  const getModelState = useCallback(
    (model: EmbeddingModel): EmbeddingModelState => {
      if (isCloud && !isConfigured) return "unconnected";
      if (model.modelName === selectedModelName) return "selected";
      if (model.modelName === currentModelName) return "current";
      return "connected";
    },
    [isCloud, isConfigured, selectedModelName, currentModelName]
  );

  const handleModelSelect = useCallback(
    (model: EmbeddingModel) => {
      if (provider.deprecated) return;
      const state = getModelState(model);

      if (state === "selected" || state === "current") {
        onDeselectModel();
        return;
      }

      if (state === "unconnected" && isCloud) {
        setPendingConnectModel(model);
        connectModal.toggle(true);
        return;
      }

      onSelectModel(model.modelName);
    },
    [
      getModelState,
      onSelectModel,
      onDeselectModel,
      connectModal,
      provider.deprecated,
      isCloud,
      setPendingConnectModel,
    ]
  );

  return (
    <>
      {isCloud && (
        <>
          <disconnectModal.Provider>
            <ConfirmationModalLayout
              icon={SvgUnplug}
              title={t("providerGroup.disconnectModal.title", {
                provider: provider.displayName,
              })}
              submit={
                <Button variant="danger" onClick={handleDisconnect}>
                  {t("providerGroup.disconnectModal.submit.label")}
                </Button>
              }
            >
              <Text font="main-ui-body" color="text-03" as="p">
                {markdown(
                  t("providerGroup.disconnectModal.description", {
                    provider: provider.displayName,
                  })
                )}
              </Text>
            </ConfirmationModalLayout>
          </disconnectModal.Provider>

          <connectModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              onSubmit={async (customModel) => {
                await mutate(SWR_KEYS.embeddingProviders);
                if (pendingConnectModel) {
                  onSelectModel(pendingConnectModel.modelName, customModel);
                  setPendingConnectModel(null);
                }
                connectModal.toggle(false);
              }}
            />
          </connectModal.Provider>

          <editCredentialsModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              existingCredentials={existingCredentials}
              existingModel={existingModel}
              onSubmit={async () => {
                await mutate(SWR_KEYS.embeddingProviders);
                editCredentialsModal.toggle(false);
              }}
            />
          </editCredentialsModal.Provider>
        </>
      )}

      <providerCreationModal.Provider>
        <ProviderCredentialsModal
          provider={provider}
          onSubmit={async (customModel) => {
            await mutate(SWR_KEYS.embeddingProviders);
            // Providers with no pre-registered models (LiteLLM / Azure) define
            // their model spec right here — stage it so the user can apply it.
            // Without this the provider row is saved but the model is dropped,
            // so no search-settings row is ever created.
            if (customModel?.modelName) {
              onSelectModel(customModel.modelName, customModel);
            }
            providerCreationModal.toggle(false);
          }}
        />
      </providerCreationModal.Provider>

      <GeneralLayouts.Section gap={1}>
        <div className="px-1 pt-1 w-full h-(--height-line-h1-headline)">
          <GeneralLayouts.Section flexDirection="row" gap={0}>
            <Spacer orientation="horizontal" rem={0.675} />
            <div className="flex flex-row justify-between items-center w-full py-1">
              <Content
                icon={provider.icon}
                title={
                  provider.docsLink
                    ? markdown(
                        `[${provider.displayName}](${provider.docsLink})`
                      )
                    : provider.displayName
                }
                suffix={
                  provider.deprecated
                    ? t("providerGroup.deprecated.suffix")
                    : undefined
                }
                sizePreset="secondary"
              />

              {isCloud && isConfigured ? (
                <GeneralLayouts.Section flexDirection="row" gap={1} width="fit">
                  <Button
                    icon={SvgUnplug}
                    prominence="tertiary"
                    size="sm"
                    disabled={providerGroupContainsCurrentModelName}
                    tooltip={
                      providerGroupContainsCurrentModelName
                        ? t("providerGroup.disconnectButton.disabledTooltip")
                        : undefined
                    }
                    onClick={() => disconnectModal.toggle(true)}
                  />
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    size="sm"
                    aria-label={t("providerGroup.editCredentialsButton.label")}
                    tooltip={t("providerGroup.editCredentialsButton.label")}
                    onClick={() => editCredentialsModal.toggle(true)}
                  />
                  <Spacer orientation="horizontal" rem={0.25} />
                </GeneralLayouts.Section>
              ) : undefined}
            </div>
          </GeneralLayouts.Section>
        </div>

        {models.length === 0 ? (
          <SelectCard
            state="filled"
            rounding={3}
            padding={2}
            onClick={() => providerCreationModal.toggle(true)}
          >
            <ContentAction
              title={t("providerGroup.addConfig.title", {
                provider: provider.displayName,
              })}
              sizePreset="secondary"
              variant="body"
              color="muted"
              padding={1}
              rightChildren={
                <Button
                  prominence="tertiary"
                  rightIcon={SvgPlusCircle}
                  onClick={() => providerCreationModal.toggle(true)}
                >
                  {t("providerGroup.addConfig.button.label")}
                </Button>
              }
              center
            />
          </SelectCard>
        ) : (
          models.map((model) => {
            const state = getModelState(model);
            const isPrioritized =
              state === "selected" ||
              (state === "current" && !selectedModelName);
            return (
              <EmbeddingModelCard
                key={model.modelName}
                model={model}
                provider={provider}
                modelState={state}
                cardState={isPrioritized ? "selected" : "filled"}
                onSelect={() => handleModelSelect(model)}
              />
            );
          })
        )}
      </GeneralLayouts.Section>
    </>
  );
}

interface EmbeddingModelCardProps {
  provider: EmbeddingProvider;
  model: EmbeddingModel;
  modelState: EmbeddingModelState;
  cardState: "filled" | "selected";
  onSelect?: () => void;
}

function EmbeddingModelCard({
  provider,
  model,
  modelState,
  cardState,
  onSelect,
}: EmbeddingModelCardProps) {
  const t = useTranslations("admin.indexSettings");
  const topRightButton = (() => {
    switch (modelState) {
      case "unconnected":
        return (
          <Button
            prominence="tertiary"
            rightIcon={SvgArrowExchange}
            onClick={onSelect}
            disabled={provider.deprecated}
            tooltip={
              provider.deprecated
                ? t("modelCard.deprecated.connectTooltip")
                : undefined
            }
          >
            {t("modelCard.connectButton.label")}
          </Button>
        );
      case "connected":
        return (
          <Button
            prominence="tertiary"
            onClick={onSelect}
            disabled={provider.deprecated}
            tooltip={
              provider.deprecated
                ? t("modelCard.deprecated.selectTooltip")
                : undefined
            }
          >
            {t("modelCard.selectButton.label")}
          </Button>
        );
      case "current":
        return (
          <Button
            variant="action"
            prominence="tertiary"
            rightIcon={SvgCheckSquare}
            onClick={onSelect}
          >
            {t("modelCard.currentButton.label")}
          </Button>
        );
      case "selected":
        return (
          <Button
            variant="action"
            prominence="tertiary"
            rightIcon={SvgCheckSquare}
            onClick={onSelect}
          >
            {t("modelCard.selectedButton.label")}
          </Button>
        );
    }
  })();

  const isClickable =
    !provider.deprecated &&
    (modelState === "unconnected" ||
      modelState === "connected" ||
      modelState === "current" ||
      modelState === "selected");

  return (
    <SelectCard
      state={cardState}
      rounding={3}
      padding={1}
      onClick={isClickable ? onSelect : undefined}
    >
      <GeneralLayouts.Section flexDirection="row" alignItems="start">
        <GeneralLayouts.Section gap={0} padding={2} alignItems="start">
          <Content
            icon={provider.icon}
            title={model.modelName}
            description={model.description}
            sizePreset="main-ui"
            variant="section"
          />
          <div className="flex flex-row px-6 pt-2 gap-4">
            <EmbeddingProviderInfo providerName={provider.providerName} />
          </div>
        </GeneralLayouts.Section>
        {topRightButton && <div className="shrink-0">{topRightButton}</div>}
      </GeneralLayouts.Section>
    </SelectCard>
  );
}

interface IndexSettingsFormValues extends EmbeddingModelSelection {
  enable_contextual_rag: boolean;
  contextual_rag_model_configuration_id: number | null;
}

function isContextualModelOnlyChange(
  values: IndexSettingsFormValues,
  initialValues: IndexSettingsFormValues
): boolean {
  return (
    values.enable_contextual_rag &&
    values.enable_contextual_rag === initialValues.enable_contextual_rag &&
    values.contextual_rag_model_configuration_id !== null &&
    values.contextual_rag_model_configuration_id !==
      initialValues.contextual_rag_model_configuration_id &&
    isSameModelSelection(values, initialValues)
  );
}

export default function IndexSettingsPage() {
  const t = useTranslations("admin.indexSettings");
  const router = useRouter();
  const settings = useSettings();
  const editModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState(MODEL_TAB_CLOUD);
  const [switchoverType, setSwitchoverType] = useState<SwitchoverType>(
    SwitchoverType.REINDEX
  );

  const allModels = useMemo(
    () => [...CLOUD_BASED_PROVIDERS, ...SELF_HOSTED_PROVIDERS],
    []
  );

  const {
    query,
    setQuery,
    filtered: filteredProviders,
  } = useFilter(
    allModels,
    (embeddingProvider) =>
      `${embeddingProvider.displayName} ${embeddingProvider.embeddingModels
        .map((embeddingModel) => embeddingModel.modelName)
        .join(" ")}`
  );

  const { filteredCloudProviders, filteredSelfHostedProviders } =
    useMemo(() => {
      const matched = new Set(filteredProviders);
      return {
        filteredCloudProviders: CLOUD_BASED_PROVIDERS.filter((p) =>
          matched.has(p)
        ),
        filteredSelfHostedProviders: SELF_HOSTED_PROVIDERS.filter((p) =>
          matched.has(p)
        ),
      };
    }, [filteredProviders]);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      if (!settings) return;

      try {
        await saveAdminSettings({ ...toSettings(settings), ...updates });
        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success(t("toasts.settingsUpdated"));
      } catch {
        toast.error(t("toasts.settingsUpdateFailed"));
      }
    },
    [settings, router, t]
  );

  const imageProcessingEnabled =
    settings.image_extraction_and_analysis_enabled ?? false;

  const { data: secondarySearchSettings } = useSecondarySearchSettings();
  // INSTANT switchover swaps immediately — no secondary settings — and backfills on the
  // current index. The reindex-progress endpoint still reports that active port target,
  // so treat it as reindexing too; otherwise the banner never shows for INSTANT.
  const { data: reindexProgress } = useReindexProgress({
    pollIntervalMs: 5000,
  });
  const isPortBackfilling =
    !secondarySearchSettings && (reindexProgress?.total ?? 0) > 0;
  const isReindexing = !!secondarySearchSettings || isPortBackfilling;

  // When a migration finishes, the fast poll on the current settings stops in
  // the same render — revalidate once so the new model shows as current.
  const wasReindexingRef = useRef(false);
  useEffect(() => {
    if (wasReindexingRef.current && !isReindexing) {
      mutate(SWR_KEYS.currentSearchSettings);
    }
    wasReindexingRef.current = isReindexing;
  }, [isReindexing]);

  // Shares the current-settings SWR key, which useCurrentSearchSettings
  // below already polls while reindexing — one timer drives both hooks.
  const { data: currentEmbeddingModel, isLoading: isLoadingCurrentModel } =
    useCurrentEmbeddingModel();

  /**
   * Camel-cased view of the active embedding model for modal preload.
   * Consumed by `LiteLLMProviderModal` and `CustomSelfHostedModal`.
   * See `ProviderModalProps.existingModel`.
   */
  const currentEmbeddingModelSpec: EmbeddingModel | null = useMemo(() => {
    if (!currentEmbeddingModel) return null;
    return {
      modelName: currentEmbeddingModel.model_name,
      modelDim: currentEmbeddingModel.model_dim,
      normalize: currentEmbeddingModel.normalize,
      queryPrefix: currentEmbeddingModel.query_prefix,
      passagePrefix: currentEmbeddingModel.passage_prefix,
      description: "",
    };
  }, [currentEmbeddingModel]);

  const currentProviderName = currentEmbeddingModel
    ? resolveProviderName(
        currentEmbeddingModel.model_name,
        currentEmbeddingModel.provider_type
      )
    : null;
  const currentProvider = currentProviderName
    ? findProvider(currentProviderName)
    : null;
  const isCurrentCloudBased = currentProviderName
    ? isCloudBased(currentProviderName)
    : false;

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useCurrentSearchSettings({ pollIntervalMs: isReindexing ? 5000 : 0 });
  const { data: configuredProvidersList } = useConfiguredEmbeddingProviders();
  const configuredProviders = useMemo(
    () =>
      new Map((configuredProvidersList ?? []).map((p) => [p.provider_type, p])),
    [configuredProvidersList]
  );
  const cancelReindexModal = useCreateModal();
  const forwardOnlyModal = useCreateModal();
  const customModelModal = useCreateModal();

  const {
    llmProviders,
    hasAnyLlm,
    hasAnyVisionLlm,
    defaultLlm,
    defaultVision,
    isLoading: isLoadingLlmProviders,
  } = useLlmDefaults();

  /**
   * Persist a new default vision model. Onyx routes all image-captioning
   * calls through `get_default_llm_with_vision()` (`backend/onyx/llm/factory.py`),
   * which reads `default_vision` — so writing here switches the model the
   * indexer uses for new captions. Existing captions stay baked into the
   * embeddings of already-indexed documents.
   */
  const handleCaptioningModelChange = useCallback(
    async ({
      modelName,
      providerName,
    }: {
      modelName: string;
      providerName: string | null;
    }) => {
      const provider = llmProviders?.find((p) => p.name === providerName);
      if (!provider) {
        toast.error(t("toasts.providerResolveFailed"));
        return;
      }
      try {
        const response = await fetch("/api/admin/llm/default-vision", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: provider.id,
            model_name: modelName,
          }),
        });
        if (!response.ok) {
          throw new Error(
            (await response.json()).detail ?? t("toasts.captioningUpdateFailed")
          );
        }
        await mutate(SWR_KEYS.llmProviders);
        toast.success(t("toasts.captioningUpdated"));
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t("toasts.unknownError")
        );
      }
    },
    [llmProviders, t]
  );

  // Resolve defaultVision (name-based) to a model_configuration_id for ModelSelector
  const captioningModelConfigId = useMemo(() => {
    if (!defaultVision?.modelName || !llmProviders) return null;
    for (const p of llmProviders) {
      if (p.name !== defaultVision.providerName) continue;
      const mc = p.model_configurations.find(
        (m) => m.name === defaultVision.modelName
      );
      if (mc?.id != null) return mc.id;
    }
    return null;
  }, [llmProviders, defaultVision]);

  const savedSelection = useMemo(
    () =>
      savedModelSelection(
        currentEmbeddingModelSpec,
        currentEmbeddingModel?.provider_type ?? null
      ),
    [currentEmbeddingModelSpec, currentEmbeddingModel]
  );

  const initialFormValues: IndexSettingsFormValues = useMemo(
    () => ({
      ...savedSelection,
      enable_contextual_rag: searchSettings?.enable_contextual_rag ?? false,
      contextual_rag_model_configuration_id:
        searchSettings?.contextual_rag_model_configuration_id ?? null,
    }),
    [savedSelection, searchSettings]
  );

  const applyContextualModelForward = useCallback(
    async (modelConfigurationId: number): Promise<boolean> => {
      if (!searchSettings) return false;

      try {
        const response = await updateInferenceSettings({
          ...searchSettings,
          contextual_rag_model_configuration_id: modelConfigurationId,
        });
        if (!response.ok) {
          toast.error(
            await parseErrorDetail(
              response,
              t("toasts.contextualModelUpdateFailed")
            )
          );
          return false;
        }

        await mutate(SWR_KEYS.currentSearchSettings);
        forwardOnlyModal.toggle(false);
        toast.success(t("toasts.contextualModelUpdated"));
        return true;
      } catch (error) {
        console.error(CONTEXTUAL_MODEL_UPDATE_LOG, error);
        toast.error(t("toasts.contextualModelUpdateFailed"));
        return false;
      }
    },
    [forwardOnlyModal, searchSettings, t]
  );

  const handleCancelReindex = useCallback(async () => {
    const response = await cancelNewEmbedding();
    if (!response.ok) {
      toast.error(t("toasts.cancelReindexFailed"));
      return;
    }
    cancelReindexModal.toggle(false);
    toast.success(t("toasts.reindexCanceled"));
    await Promise.all([
      mutate(SWR_KEYS.currentSearchSettings),
      mutate(SWR_KEYS.secondarySearchSettings),
      mutate(SWR_KEYS.indexingStatus),
      mutate(SWR_KEYS.reindexProgress),
      mutate(SWR_KEYS.reindexErrors),
    ]);
  }, [cancelReindexModal, t]);

  if (
    isLoadingCurrentModel ||
    isLoadingSearchSettings ||
    isLoadingLlmProviders
  ) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
        <SettingsLayouts.Body>
          <PageLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <>
      {currentProvider && isCurrentCloudBased && (
        <editModal.Provider>
          <ProviderCredentialsModal
            provider={currentProvider}
            existingCredentials={configuredProviders?.get(
              currentProvider.providerName
            )}
            existingModel={currentEmbeddingModelSpec ?? undefined}
            onSubmit={async () => {
              await mutate(SWR_KEYS.embeddingProviders);
              editModal.toggle(false);
            }}
          />
        </editModal.Provider>
      )}

      <cancelReindexModal.Provider>
        <ConfirmationModalLayout
          icon={SvgRevert}
          title={t("cancelReindexModal.title")}
          submit={
            <Button variant="danger" onClick={handleCancelReindex}>
              {t("cancelReindexModal.submit.label")}
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03" as="p">
            {t("cancelReindexModal.description")}
          </Text>
        </ConfirmationModalLayout>
      </cancelReindexModal.Provider>

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={t("header.description")}
          divider
        />

        <SettingsLayouts.Body>
          <Formik<IndexSettingsFormValues>
            enableReinitialize
            initialValues={initialFormValues}
            onSubmit={async (values) => {
              // Contextual Retrieval re-embeds each chunk through an LLM; with
              // the toggle on but no model chosen the port fails, so block here.
              if (
                values.enable_contextual_rag &&
                values.contextual_rag_model_configuration_id === null
              ) {
                toast.error(t("toasts.contextualModelRequired"));
                return;
              }
              const resolved = resolveModelForApply(values);
              if (!resolved) {
                toast.error(t("toasts.modelNotFound"));
                return;
              }

              const response = await setNewSearchSettings({
                model: resolved.model,
                providerName: resolved.providerName,
                switchoverType,
                enableContextualRag: values.enable_contextual_rag,
                contextualRagModelConfigurationId: values.enable_contextual_rag
                  ? values.contextual_rag_model_configuration_id
                  : null,
              });

              if (!response.ok) {
                toast.error(t("toasts.applyFailed"));
                return;
              }

              toast.success(t("toasts.reindexStarted"));
              setSwitchoverType(SwitchoverType.REINDEX);
              await Promise.all([
                mutate(SWR_KEYS.currentSearchSettings),
                mutate(SWR_KEYS.secondarySearchSettings),
              ]);
            }}
          >
            {({ values, dirty, setFieldValue, resetForm, submitForm }) => {
              const applySelection = (selection: EmbeddingModelSelection) => {
                void setFieldValue("model_name", selection.model_name);
                void setFieldValue("model_spec", selection.model_spec);
                void setFieldValue("model_provider", selection.model_provider);
              };
              const isModelStaged =
                values.model_name !== initialFormValues.model_name &&
                !!values.model_name;
              const stagedModelName = isModelStaged ? values.model_name : null;
              const statusVariant = dirty ? "warning" : undefined;
              // Block apply when Contextual Retrieval is on but no LLM is set.
              const contextualRagModelMissing =
                values.enable_contextual_rag &&
                values.contextual_rag_model_configuration_id === null;
              const contextualModelOnlyChange = isContextualModelOnlyChange(
                values,
                initialFormValues
              );
              const switchoverStrategySelect = (
                <InputSelect
                  value={switchoverType}
                  onValueChange={(v) => setSwitchoverType(v as SwitchoverType)}
                >
                  <InputSelect.Trigger
                    placeholder={t("switchover.placeholder")}
                  />
                  <InputSelect.Content>
                    <InputSelect.Item
                      value={SwitchoverType.REINDEX}
                      icon={SvgClock}
                      wrapDescription
                      description={t("switchover.reindexAll.description")}
                    >
                      {t("switchover.reindexAll.label")}
                    </InputSelect.Item>
                    <InputSelect.Item
                      value={SwitchoverType.ACTIVE_ONLY}
                      icon={SvgSlowTime}
                      wrapDescription
                      description={t("switchover.activeOnly.description")}
                    >
                      {t("switchover.activeOnly.label")}
                    </InputSelect.Item>
                    <InputSelect.Item
                      value={SwitchoverType.INSTANT}
                      icon={SvgEmpty}
                      wrapDescription
                      description={t("switchover.instant.description")}
                    >
                      {t("switchover.instant.label")}
                    </InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              );
              const revertButton = (
                <Button
                  prominence="secondary"
                  onClick={() => {
                    resetForm();
                    setSwitchoverType(SwitchoverType.REINDEX);
                  }}
                >
                  {t("actions.revert.label")}
                </Button>
              );
              const rebuildButton = (
                <Button
                  onClick={() => void submitForm()}
                  disabled={contextualRagModelMissing}
                >
                  {contextualModelOnlyChange
                    ? t("actions.rebuildAll.label")
                    : t("actions.applyReindex.label")}
                </Button>
              );

              return (
                <>
                  <forwardOnlyModal.Provider>
                    <ConfirmationModalLayout
                      icon={SvgArrowExchange}
                      title={t("forwardOnlyModal.title")}
                      submit={
                        <Button
                          onClick={async () => {
                            const modelConfigurationId =
                              values.contextual_rag_model_configuration_id;
                            if (modelConfigurationId === null) return;
                            const updated =
                              await applyContextualModelForward(
                                modelConfigurationId
                              );
                            if (updated) {
                              resetForm({ values });
                              setSwitchoverType(SwitchoverType.REINDEX);
                            }
                          }}
                        >
                          {t("actions.applyForward.label")}
                        </Button>
                      }
                    >
                      <Text font="main-ui-body" color="text-03" as="p">
                        {t("forwardOnlyModal.description")}
                      </Text>
                    </ConfirmationModalLayout>
                  </forwardOnlyModal.Provider>

                  <customModelModal.Provider>
                    <ProviderCredentialsModal
                      provider={CUSTOM_PROVIDER}
                      existingModel={
                        currentProviderName === EmbeddingProviderName.CUSTOM
                          ? (currentEmbeddingModelSpec ?? undefined)
                          : undefined
                      }
                      onSubmit={(customModel) => {
                        if (customModel?.modelName) {
                          applySelection({
                            model_name: customModel.modelName,
                            model_spec: {
                              ...customModel,
                              modelName: customModel.modelName,
                            },
                            model_provider: null,
                          });
                        }
                        customModelModal.toggle(false);
                      }}
                    />
                  </customModelModal.Provider>

                  {isReindexing ? (
                    secondarySearchSettings?.use_port_flow ||
                    isPortBackfilling ? (
                      // Port-flow reindex, or an INSTANT-switchover backfill (already
                      // swapped, no secondary) → the per-connector/user progress banner.
                      <ReindexProgressBanner
                        secondaryModelName={
                          secondarySearchSettings?.model_name ??
                          searchSettings?.model_name
                        }
                        onCancel={() => cancelReindexModal.toggle(true)}
                      />
                    ) : (
                      // Non-port reindex has no PortAttempt progress → the original banner.
                      <MessageCard
                        variant="warning"
                        headerPadding={2}
                        title={t("reindexBanner.title")}
                        description={markdown(
                          t("reindexBanner.description", {
                            model: secondarySearchSettings?.model_name ?? "",
                          })
                        )}
                        bottomChildren={
                          <GeneralLayouts.Section
                            flexDirection="row"
                            gap={2}
                            justifyContent="end"
                            padding={2}
                          >
                            <Button
                              icon={SvgExternalLink}
                              href={ADMIN_ROUTES.INDEXING_STATUS.path}
                            >
                              {t("reindexBanner.seeConnectors.label")}
                            </Button>
                            <Button
                              variant="danger"
                              prominence="secondary"
                              onClick={() => cancelReindexModal.toggle(true)}
                            >
                              {t("reindexBanner.cancelReindex.label")}
                            </Button>
                          </GeneralLayouts.Section>
                        }
                      />
                    )
                  ) : (
                    !NEXT_PUBLIC_CLOUD_ENABLED && (
                      <MessageCard
                        variant={
                          contextualRagModelMissing ? "error" : statusVariant
                        }
                        headerPadding={2}
                        title={
                          contextualRagModelMissing
                            ? t("changesBanner.contextualModelMissing.title")
                            : contextualModelOnlyChange
                              ? t("changesBanner.contextualModelOnly.title")
                              : t("changesBanner.default.title")
                        }
                        description={markdown(
                          contextualRagModelMissing
                            ? t(
                                "changesBanner.contextualModelMissing.description"
                              )
                            : contextualModelOnlyChange
                              ? t(
                                  "changesBanner.contextualModelOnly.description"
                                )
                              : t("changesBanner.default.description")
                        )}
                        bottomChildren={
                          dirty ? (
                            contextualModelOnlyChange ? (
                              <GeneralLayouts.Section
                                flexDirection="row"
                                alignItems="center"
                                gap={2}
                                padding={2}
                                height="fit"
                              >
                                <GeneralLayouts.Section
                                  flexDirection="row"
                                  gap={2}
                                  width="fit"
                                  height="fit"
                                >
                                  {revertButton}
                                  <Button
                                    prominence="secondary"
                                    onClick={() =>
                                      forwardOnlyModal.toggle(true)
                                    }
                                  >
                                    {t("actions.applyForward.label")}
                                  </Button>
                                </GeneralLayouts.Section>
                                <Text
                                  font="secondary-body"
                                  color="text-03"
                                  nowrap
                                >
                                  {t("changesBanner.orSeparator.label")}
                                </Text>
                                <GeneralLayouts.Section
                                  flexDirection="row"
                                  gap={2}
                                  height="fit"
                                  className="flex-1 min-w-0"
                                >
                                  <GeneralLayouts.Section
                                    height="fit"
                                    alignItems="stretch"
                                    className="flex-1 min-w-0"
                                  >
                                    {switchoverStrategySelect}
                                  </GeneralLayouts.Section>
                                  {rebuildButton}
                                </GeneralLayouts.Section>
                              </GeneralLayouts.Section>
                            ) : (
                              <div className="flex flex-row items-end gap-4 p-2">
                                <div className="flex-1 min-w-0">
                                  {switchoverStrategySelect}
                                </div>
                                <div className="flex flex-row gap-2 shrink-0">
                                  {revertButton}
                                  {rebuildButton}
                                </div>
                              </div>
                            )
                          ) : undefined
                        }
                      />
                    )
                  )}

                  {/* Inner Disabled/CloudDisabled wrappers AND !isReindexing so opal's
                      disabled opacity doesn't compound to 25% under this one. */}
                  <Disabled
                    disabled={isReindexing}
                    tooltip={t("reindexing.disabledTooltip")}
                  >
                    <div className="flex w-full flex-col gap-8">
                      {/* ── Embedding Model ── */}
                      <GeneralLayouts.Section
                        gap={3}
                        height="fit"
                        alignItems="stretch"
                        justifyContent="start"
                      >
                        <Content
                          title={t("embeddingModel.title")}
                          description={t("embeddingModel.description")}
                          sizePreset="main-content"
                          variant="section"
                        />

                        {NEXT_PUBLIC_CLOUD_ENABLED ? (
                          <CloudDisabled>
                            <Card border="solid" rounding={4} padding={2}>
                              <GeneralLayouts.Section padding={2}>
                                <Content
                                  icon={SvgVector}
                                  title={t("embeddingModel.cloudManaged.title")}
                                  sizePreset="main-ui"
                                  variant="section"
                                />
                              </GeneralLayouts.Section>
                            </Card>
                          </CloudDisabled>
                        ) : (
                          currentEmbeddingModel && (
                            <Tabs
                              value={activeModelTab}
                              onValueChange={setActiveModelTab}
                              variant="underline"
                            >
                              <Card
                                expandable
                                expanded={viewAllModelsOpen}
                                expandableContentHeight="fit"
                                border="solid"
                                borderColor={statusVariant}
                                rounding={4}
                                padding={viewAllModelsOpen ? 0 : 2}
                                expandedContent={
                                  <>
                                    <Tabs.Content value={MODEL_TAB_CLOUD}>
                                      {filteredCloudProviders.length > 0 ? (
                                        <GeneralLayouts.Section
                                          gap={2}
                                          padding={2}
                                        >
                                          {filteredCloudProviders.map(
                                            (provider) => (
                                              <ProviderGroup
                                                key={provider.providerName}
                                                provider={provider}
                                                currentModelName={
                                                  currentEmbeddingModel?.model_name
                                                }
                                                selectedModelName={
                                                  stagedModelName ?? undefined
                                                }
                                                isCloud
                                                existingCredentials={configuredProviders?.get(
                                                  provider.providerName
                                                )}
                                                existingModel={
                                                  currentEmbeddingModel?.provider_type ===
                                                  provider.providerName
                                                    ? (currentEmbeddingModelSpec ??
                                                      undefined)
                                                    : undefined
                                                }
                                                onSelectModel={(
                                                  name,
                                                  customModel
                                                ) =>
                                                  applySelection({
                                                    model_name: name,
                                                    model_spec: customModel
                                                      ? {
                                                          ...customModel,
                                                          modelName: name,
                                                        }
                                                      : null,
                                                    model_provider: customModel
                                                      ? provider.providerName
                                                      : null,
                                                  })
                                                }
                                                onDeselectModel={() =>
                                                  applySelection(savedSelection)
                                                }
                                              />
                                            )
                                          )}
                                        </GeneralLayouts.Section>
                                      ) : (
                                        <IllustrationContent
                                          illustration={SvgNoResult}
                                          title={t(
                                            "modelPicker.noCloudResults.title"
                                          )}
                                          description={t(
                                            "modelPicker.noResults.description"
                                          )}
                                        />
                                      )}
                                    </Tabs.Content>

                                    <Tabs.Content value={MODEL_TAB_SELF}>
                                      {filteredSelfHostedProviders.length >
                                      0 ? (
                                        <GeneralLayouts.Section
                                          gap={2}
                                          padding={2}
                                        >
                                          {filteredSelfHostedProviders.map(
                                            (shProvider) => (
                                              <ProviderGroup
                                                key={shProvider.providerName}
                                                provider={shProvider}
                                                currentModelName={
                                                  currentEmbeddingModel?.model_name
                                                }
                                                selectedModelName={
                                                  stagedModelName ?? undefined
                                                }
                                                onSelectModel={(name) =>
                                                  applySelection({
                                                    model_name: name,
                                                    model_spec: null,
                                                    model_provider: null,
                                                  })
                                                }
                                                onDeselectModel={() =>
                                                  applySelection(savedSelection)
                                                }
                                              />
                                            )
                                          )}

                                          <GeneralLayouts.Section gap={1}>
                                            <div className="px-1 pt-1 w-full h-(--height-line-h1-headline)">
                                              <GeneralLayouts.Section
                                                flexDirection="row"
                                                gap={0}
                                              >
                                                <Spacer
                                                  orientation="horizontal"
                                                  rem={0.675}
                                                />
                                                <div className="flex flex-row justify-between items-center w-full py-1">
                                                  <Content
                                                    icon={CUSTOM_PROVIDER.icon}
                                                    title={t(
                                                      "modelPicker.customModels.title"
                                                    )}
                                                    sizePreset="secondary"
                                                  />
                                                </div>
                                              </GeneralLayouts.Section>
                                            </div>

                                            <SelectCard
                                              state="filled"
                                              rounding={3}
                                              padding={2}
                                              onClick={() =>
                                                customModelModal.toggle(true)
                                              }
                                            >
                                              <ContentAction
                                                title={t(
                                                  "modelPicker.customModel.title"
                                                )}
                                                sizePreset="secondary"
                                                variant="body"
                                                color="muted"
                                                padding={1}
                                                rightChildren={
                                                  <Button
                                                    prominence="tertiary"
                                                    rightIcon={SvgPlusCircle}
                                                    onClick={() =>
                                                      customModelModal.toggle(
                                                        true
                                                      )
                                                    }
                                                  >
                                                    {t(
                                                      "modelPicker.addCustomModel.label"
                                                    )}
                                                  </Button>
                                                }
                                                center
                                              />
                                            </SelectCard>
                                          </GeneralLayouts.Section>
                                        </GeneralLayouts.Section>
                                      ) : (
                                        <IllustrationContent
                                          illustration={SvgNoResult}
                                          title={t(
                                            "modelPicker.noSelfHostedResults.title"
                                          )}
                                          description={t(
                                            "modelPicker.noResults.description"
                                          )}
                                        />
                                      )}
                                    </Tabs.Content>
                                  </>
                                }
                              >
                                {viewAllModelsOpen ? (
                                  <div className="pt-1 px-1">
                                    <div className="pt-2 pb-1 px-2 flex flex-row items-center justify-between">
                                      <InputTypeIn
                                        placeholder={t(
                                          "modelPicker.search.placeholder"
                                        )}
                                        variant="internal"
                                        searchIcon
                                        value={query}
                                        onChange={(e) =>
                                          setQuery(e.target.value)
                                        }
                                      />
                                      <div className="flex flex-row">
                                        {isModelStaged && (
                                          <Button
                                            icon={SvgRevert}
                                            prominence="internal"
                                            tooltip={t(
                                              "modelPicker.revertSelection.tooltip"
                                            )}
                                            onClick={() =>
                                              applySelection(savedSelection)
                                            }
                                          />
                                        )}
                                        <Button
                                          prominence="internal"
                                          onClick={() =>
                                            setViewAllModelsOpen(false)
                                          }
                                          rightIcon={SvgFold}
                                        >
                                          {t("modelPicker.foldModels.label")}
                                        </Button>
                                      </div>
                                    </div>

                                    <div className="px-2">
                                      <Tabs.List>
                                        <Tabs.Trigger value={MODEL_TAB_CLOUD}>
                                          {t("modelPicker.cloudTab.label")}
                                        </Tabs.Trigger>
                                        <Tabs.Trigger value={MODEL_TAB_SELF}>
                                          {t("modelPicker.selfHostedTab.label")}
                                        </Tabs.Trigger>
                                      </Tabs.List>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="flex flex-row items-start w-full">
                                    <GeneralLayouts.Section
                                      padding={2}
                                      gap={0}
                                      alignItems="start"
                                    >
                                      <Content
                                        icon={
                                          currentProvider?.icon ?? SvgServer
                                        }
                                        title={currentEmbeddingModel.model_name}
                                        description={
                                          findRegistryModel(
                                            currentEmbeddingModel.model_name
                                          )?.description
                                        }
                                        sizePreset="main-ui"
                                        variant="section"
                                      />
                                      <div className="flex flex-row items-center gap-2 pt-2 px-6">
                                        {currentProviderName && (
                                          <EmbeddingProviderInfo
                                            providerName={currentProviderName}
                                          />
                                        )}
                                      </div>
                                    </GeneralLayouts.Section>

                                    <div className="flex flex-col justify-start items-end shrink-0 gap-1 p-2">
                                      <Button
                                        prominence="secondary"
                                        onClick={() => {
                                          const isStagedSelfHosted =
                                            stagedModelName &&
                                            SELF_HOSTED_PROVIDERS.some((p) =>
                                              p.embeddingModels.some(
                                                (m) =>
                                                  m.modelName ===
                                                  stagedModelName
                                              )
                                            );
                                          setActiveModelTab(
                                            isStagedSelfHosted
                                              ? MODEL_TAB_SELF
                                              : stagedModelName
                                                ? MODEL_TAB_CLOUD
                                                : currentEmbeddingModel?.provider_type
                                                  ? MODEL_TAB_CLOUD
                                                  : MODEL_TAB_SELF
                                          );
                                          setViewAllModelsOpen(true);
                                        }}
                                      >
                                        {t("modelPicker.viewAllModels.label")}
                                      </Button>
                                      {isCurrentCloudBased && (
                                        <div className="p-1">
                                          <Button
                                            icon={SvgSettings}
                                            prominence="tertiary"
                                            size="md"
                                            onClick={() =>
                                              editModal.toggle(true)
                                            }
                                          />
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                )}
                              </Card>
                            </Tabs>
                          )
                        )}
                      </GeneralLayouts.Section>

                      <Divider paddingParallel={0} paddingPerpendicular={0} />

                      {/* ── Retrieval Optimization ── */}
                      <GeneralLayouts.Section
                        gap={3}
                        height="fit"
                        alignItems="stretch"
                        justifyContent="start"
                      >
                        <Content
                          title={t("retrieval.title")}
                          description={t("retrieval.description")}
                          sizePreset="main-content"
                          variant="section"
                        />

                        <CloudDisabled
                          disabled={!isReindexing}
                          tooltip={t("multipass.disabledTooltip")}
                        >
                          <Card border="solid" rounding={4}>
                            <InputHorizontal
                              title={t("multipass.title")}
                              description={t("multipass.description")}
                              tag={{
                                title: t("multipass.tag.label"),
                                color: "gray",
                              }}
                              withLabel
                            >
                              <Switch
                                checked={
                                  searchSettings?.multipass_indexing ?? false
                                }
                                disabled
                              />
                            </InputHorizontal>
                          </Card>
                        </CloudDisabled>

                        <CloudDisabled
                          disabled={!hasAnyLlm && !isReindexing}
                          tooltip={
                            !hasAnyLlm
                              ? markdown(
                                  t("contextualRetrieval.noModelsTooltip", {
                                    link: ADMIN_ROUTES.LLM_MODELS.path,
                                  })
                                )
                              : undefined
                          }
                        >
                          <Card
                            border="solid"
                            borderColor={statusVariant}
                            rounding={4}
                          >
                            <GeneralLayouts.Section
                              width="full"
                              alignItems="stretch"
                            >
                              <InputHorizontal
                                title={t("contextualRetrieval.title")}
                                description={t(
                                  "contextualRetrieval.description"
                                )}
                                withLabel
                              >
                                <SwitchField name="enable_contextual_rag" />
                              </InputHorizontal>

                              <Disabled
                                disabled={
                                  !values.enable_contextual_rag && !isReindexing
                                }
                                tooltip={t("contextualModel.disabledTooltip")}
                              >
                                <InputHorizontal
                                  title={t("contextualModel.title")}
                                  description={t("contextualModel.description")}
                                  disabled={!values.enable_contextual_rag}
                                  withLabel
                                >
                                  <ModelSelector
                                    value={
                                      values.contextual_rag_model_configuration_id
                                    }
                                    disabled={!values.enable_contextual_rag}
                                    onChange={(opt) =>
                                      void setFieldValue(
                                        "contextual_rag_model_configuration_id",
                                        opt.modelConfigurationId ?? null
                                      )
                                    }
                                  />
                                </InputHorizontal>
                              </Disabled>
                            </GeneralLayouts.Section>
                          </Card>
                        </CloudDisabled>
                      </GeneralLayouts.Section>

                      <Divider paddingParallel={0} paddingPerpendicular={0} />

                      {/* ── Image Processing ── */}
                      <GeneralLayouts.Section
                        gap={3}
                        height="fit"
                        alignItems="stretch"
                        justifyContent="start"
                      >
                        <Content
                          title={t("imageProcessing.title")}
                          description={t("imageProcessing.description")}
                          sizePreset="main-content"
                          variant="section"
                        />

                        <Disabled
                          disabled={!hasAnyVisionLlm && !isReindexing}
                          tooltip={
                            !hasAnyVisionLlm
                              ? markdown(
                                  t("imageProcessing.noVisionModelsTooltip", {
                                    link: ADMIN_ROUTES.LLM_MODELS.path,
                                  })
                                )
                              : undefined
                          }
                        >
                          <Card border="solid" rounding={4}>
                            <GeneralLayouts.Section
                              width="full"
                              alignItems="stretch"
                            >
                              <InputHorizontal
                                title={t("imageExtraction.title")}
                                description={t("imageExtraction.description")}
                                withLabel
                              >
                                <Switch
                                  checked={imageProcessingEnabled}
                                  onCheckedChange={(checked) => {
                                    void saveSettings({
                                      image_extraction_and_analysis_enabled:
                                        checked,
                                    });
                                  }}
                                />
                              </InputHorizontal>

                              <Disabled
                                disabled={
                                  !imageProcessingEnabled && !isReindexing
                                }
                                tooltip={t(
                                  "imageProcessing.enableFirstTooltip"
                                )}
                              >
                                <InputHorizontal
                                  title={t("captioningModel.title")}
                                  description={t("captioningModel.description")}
                                  disabled={!imageProcessingEnabled}
                                  withLabel
                                >
                                  <ModelSelector
                                    value={captioningModelConfigId}
                                    disabled={!imageProcessingEnabled}
                                    requiresImageInput
                                    onChange={(opt) =>
                                      void handleCaptioningModelChange({
                                        modelName: opt.modelName,
                                        providerName: opt.name,
                                      })
                                    }
                                  />
                                </InputHorizontal>
                              </Disabled>

                              <Disabled
                                disabled={
                                  !imageProcessingEnabled && !isReindexing
                                }
                                tooltip={t(
                                  "imageProcessing.enableFirstTooltip"
                                )}
                              >
                                <InputHorizontal
                                  title={t("maxImageSize.title")}
                                  suffix={t("maxImageSize.suffix")}
                                  description={t("maxImageSize.description")}
                                  disabled={!imageProcessingEnabled}
                                  withLabel
                                >
                                  <InputSelect
                                    value={String(
                                      settings.image_analysis_max_size_mb ?? 20
                                    )}
                                    onValueChange={(value) => {
                                      void saveSettings({
                                        image_analysis_max_size_mb: parseInt(
                                          value,
                                          10
                                        ),
                                      });
                                    }}
                                    disabled={!imageProcessingEnabled}
                                  >
                                    <InputSelect.Trigger />
                                    <InputSelect.Content>
                                      {MAX_IMAGE_SIZE_OPTIONS.map((size) => (
                                        <InputSelect.Item
                                          key={size}
                                          value={size}
                                        >
                                          {size}
                                        </InputSelect.Item>
                                      ))}
                                    </InputSelect.Content>
                                  </InputSelect>
                                </InputHorizontal>
                              </Disabled>
                            </GeneralLayouts.Section>
                          </Card>
                        </Disabled>
                      </GeneralLayouts.Section>
                    </div>
                  </Disabled>
                </>
              );
            }}
          </Formik>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </>
  );
}
