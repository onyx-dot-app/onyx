"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Formik } from "formik";
import { markdown } from "@opal/utils";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { PageLoader } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ErrorResponseBody } from "@/lib/fetcher";
import { useConnectorIndexingStatusWithPagination } from "@/lib/hooks";
import type { ConnectorIndexingStatusLite } from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import { Content, IllustrationContent, StickyBox, toast } from "@opal/layouts";
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
  InputSwitch,
  Tabs,
  Text,
  type SelectDivider,
  type SelectOptions,
} from "@opal/components";
import {
  SvgAlertTriangle,
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
  SvgTrash,
  SvgUnplug,
  SvgVector,
} from "@opal/icons";
import SwitchField from "@/refresh-components/form/SwitchField";
import { InputSingleSelect } from "@opal/components";
import { InputSingleSelectField } from "@opal/form";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import {
  EmbeddingProviderName,
  SwitchoverType,
  VectorQuantization,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingModelRequest,
  type EmbeddingModelSelection,
  type EmbeddingModelState,
  type EmbeddingProvider,
} from "@/lib/searchSettings/types";
import {
  CLOUD_BASED_PROVIDERS,
  CUSTOM_PROVIDER,
  DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB,
  MAX_IMAGE_SIZE_OPTIONS,
  SELF_HOSTED_PROVIDERS,
} from "@/lib/searchSettings/constants";
import {
  embeddingModelDescription,
  findProvider,
  findRegistryModel,
  isCloudBased,
  resolveProviderName,
} from "@/lib/searchSettings";
import {
  isSameModelSelection,
  resolveModelForApply,
  savedModelSelection,
} from "@/lib/searchSettings/utils";
import {
  saveAdminSettings,
  cancelNewEmbedding,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
  updateInferenceSettings,
} from "@/lib/searchSettings/svc";
import { useCreateModal } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { ConfirmationModalLayout } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { findProviderOwningModelConfig } from "@/lib/languageModels/utils";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useReindexProgress,
  useSecondarySearchSettings,
} from "@/lib/searchSettings/hooks";
import { useLlmDefaults } from "@/lib/languageModels/hooks";
import useFilter from "@/hooks/useFilter";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import {
  filterModelConfigurations,
  findLlmOptionById,
} from "@/lib/languageModels/options";
import type { RichStr } from "@opal/types";
import { ProviderCredentialsModal } from "@/views/admin/IndexSettingsPage/modals";
import ReindexProgressBanner from "@/views/admin/IndexSettingsPage/ReindexProgressBanner";
import { parseErrorDetail } from "@/lib/fetcher";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MODEL_TAB_CLOUD = "cloud-based";
const MODEL_TAB_SELF = "self-hosted";
// Developer-facing log label only; the user-visible copy comes from `t`.
const CONTEXTUAL_MODEL_UPDATE_LOG = "Failed to update Contextual Retrieval LLM";

// Mirrors the backend's compute_wont_port_cc_pair_ids, so the modal shows the admin the
// same set the server will delete. The two have to be changed together.
function computeWontPortConnectors(
  statuses: ConnectorIndexingStatusLite[],
  switchoverType: SwitchoverType
): ConnectorIndexingStatusLite[] {
  return statuses.filter((s) => {
    if (s.cc_pair_status === ConnectorCredentialPairStatus.INVALID) {
      return true;
    }
    return (
      s.cc_pair_status === ConnectorCredentialPairStatus.PAUSED &&
      switchoverType === SwitchoverType.ACTIVE_ONLY
    );
  });
}

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
  const { appName } = useSettings();
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
            description={embeddingModelDescription(model, t, appName)}
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
  vector_quantization: VectorQuantization;
  image_processing_enabled: boolean;
  image_processing_model_configuration_id: number | null;
  image_processing_max_size_mb: number;
}

/**
 * The fourth apply strategy: save the staged settings and start nothing.
 * Offered only while Image Processing is the only section that changed; the
 * backend only ever sees a `SwitchoverType`.
 */
const DO_NOT_REINDEX = "do_not_reindex";
type ApplyStrategy = SwitchoverType | typeof DO_NOT_REINDEX;
const APPLY_STRATEGIES: readonly ApplyStrategy[] = [
  DO_NOT_REINDEX,
  SwitchoverType.REINDEX,
  SwitchoverType.ACTIVE_ONLY,
  SwitchoverType.INSTANT,
];

function isApplyStrategy(value: string): value is ApplyStrategy {
  return APPLY_STRATEGIES.some((strategy) => strategy === value);
}

function toSwitchoverType(strategy: ApplyStrategy): SwitchoverType {
  return strategy === DO_NOT_REINDEX ? SwitchoverType.REINDEX : strategy;
}

interface IndexSettingsChanges {
  embeddingChanged: boolean;
  contextualToggleChanged: boolean;
  /** Contextual Retrieval stays on and points at a different model. */
  contextualModelChanged: boolean;
  /** Part of the index mapping, so it always needs a re-index. */
  quantizationChanged: boolean;
  imageChanged: boolean;
  /** Any of the above. Formik's `dirty` also counts a change undone by hand. */
  any: boolean;
}

function classifyChanges(
  values: IndexSettingsFormValues,
  initialValues: IndexSettingsFormValues
): IndexSettingsChanges {
  // The model and the size only matter while the feature is on, so switching
  // on, picking a model and switching back off stages nothing, and the pick
  // survives in the form for a later re-enable.
  const imageChanged =
    values.image_processing_enabled !==
      initialValues.image_processing_enabled ||
    (values.image_processing_enabled &&
      (values.image_processing_model_configuration_id !==
        initialValues.image_processing_model_configuration_id ||
        values.image_processing_max_size_mb !==
          initialValues.image_processing_max_size_mb));
  const embeddingChanged = !isSameModelSelection(values, initialValues);
  const contextualToggleChanged =
    values.enable_contextual_rag !== initialValues.enable_contextual_rag;
  const contextualModelChanged =
    values.enable_contextual_rag &&
    initialValues.enable_contextual_rag &&
    values.contextual_rag_model_configuration_id !== null &&
    values.contextual_rag_model_configuration_id !==
      initialValues.contextual_rag_model_configuration_id;
  const quantizationChanged =
    values.vector_quantization !== initialValues.vector_quantization;
  return {
    embeddingChanged,
    contextualToggleChanged,
    contextualModelChanged,
    quantizationChanged,
    imageChanged,
    any:
      embeddingChanged ||
      contextualToggleChanged ||
      contextualModelChanged ||
      quantizationChanged ||
      imageChanged,
  };
}

/**
 * Which banner the staged changes get. An embedding or contextual-toggle
 * change needs a re-index; a contextual model change on its own offers the
 * forward-only pair; image processing on its own may skip re-indexing.
 */
type BannerMode = "reindex" | "contextualModelOnly" | "imageOnly";

function bannerModeFor(changes: IndexSettingsChanges): BannerMode {
  if (
    changes.embeddingChanged ||
    changes.contextualToggleChanged ||
    changes.quantizationChanged
  ) {
    return "reindex";
  }
  if (changes.contextualModelChanged) return "contextualModelOnly";
  if (changes.imageChanged) return "imageOnly";
  return "reindex";
}

/**
 * The strategy the dropdown shows. `null` means the admin has not chosen, so
 * the least destructive option for the banner mode stands in. A stored
 * "do not re-index" cannot survive a mode that no longer offers it.
 */
function resolveApplyStrategy(
  stored: ApplyStrategy | null,
  mode: BannerMode
): ApplyStrategy {
  if (mode === "imageOnly") return stored ?? DO_NOT_REINDEX;
  return stored === null || stored === DO_NOT_REINDEX
    ? SwitchoverType.REINDEX
    : stored;
}

type ImagePersistResult = "skipped" | "saved" | "failed";

export default function IndexSettingsPage() {
  const t = useTranslations("admin.indexSettings");
  const tInputSelect = useTranslations("common.inputSelect");
  const adminRouteTitle = useAdminRouteTitle();
  const router = useRouter();
  const settings = useSettings();
  const editModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState(MODEL_TAB_CLOUD);
  // The admin's explicit pick in the strategy dropdown; null until they pick.
  const [applyStrategy, setApplyStrategy] = useState<ApplyStrategy | null>(
    null
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
  const wontPortConsentModal = useCreateModal();

  // SWR reports isLoading=false the instant it serves a cached list, so stale statuses can
  // look ready. Staying subscribed through a reindex, rather than pausing and resuming the
  // hook, keeps the 30s poll refreshing them. Cloud skips this and has no banner.
  const {
    data: indexingStatusData,
    isLoading: isLoadingStatuses,
    isValidating: isValidatingStatuses,
    error: statusesError,
  } = useConnectorIndexingStatusWithPagination(
    { get_all_connectors: true },
    30000,
    !NEXT_PUBLIC_CLOUD_ENABLED
  );
  const connectorStatuses = useMemo<ConnectorIndexingStatusLite[]>(
    () =>
      (indexingStatusData ?? [])
        .flatMap((group) => group.indexing_statuses)
        // Federated entries have no cc_pair — they aren't port-tracked, so drop them.
        .filter((s): s is ConnectorIndexingStatusLite => "cc_pair_status" in s),
    [indexingStatusData]
  );
  // Frozen when Apply is pressed, and read by both the modal and the submitted
  // acknowledgement, so a background poll can't grow the set under an open confirmation.
  // A ref rather than state so the no-modal path can submit the value it just froze.
  const frozenWontPortRef = useRef<ConnectorIndexingStatusLite[]>([]);
  // Waits for the mount revalidation to settle, not just for isLoading to clear, so a
  // cached list can't pass as ready. Later 30s polls leave this true, so Apply doesn't
  // flicker between enabled and disabled.
  const [statusesSettled, setStatusesSettled] = useState(false);
  useEffect(() => {
    if (!isLoadingStatuses && !isValidatingStatuses) setStatusesSettled(true);
  }, [isLoadingStatuses, isValidatingStatuses]);
  // An empty won't-port set before the statuses arrive is a false empty, and submitting on
  // it skips the consent modal only to be rejected by the server's drift check.
  const connectorStatusesReady = statusesSettled && !statusesError;

  const {
    llmProviders,
    hasAnyLlm,
    hasAnyVisionLlm,
    defaultLlm,
    defaultVision,
    isLoading: isLoadingLlmProviders,
  } = useLlmDefaults();

  // Resolve defaultVision to a model_configuration_id for the picker. Keyed on
  // providerId: display names are not unique, so a name match can land on a
  // provider that does not own this model.
  const captioningModelConfigId = useMemo(() => {
    if (!defaultVision?.modelName || !llmProviders) return null;
    const provider = llmProviders.find(
      (p) => p.id === defaultVision.providerId
    );
    const mc = provider?.model_configurations.find(
      (m) => m.name === defaultVision.modelName
    );
    return mc?.id ?? null;
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
      vector_quantization:
        searchSettings?.vector_quantization ?? VectorQuantization.NONE,
      image_processing_enabled:
        settings.image_extraction_and_analysis_enabled ?? false,
      image_processing_model_configuration_id: captioningModelConfigId,
      image_processing_max_size_mb:
        settings.image_analysis_max_size_mb ??
        DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB,
    }),
    [
      savedSelection,
      searchSettings,
      settings.image_extraction_and_analysis_enabled,
      settings.image_analysis_max_size_mb,
      captioningModelConfigId,
    ]
  );

  /**
   * Save the staged image processing settings, if any changed. The model
   * goes first, through the vision default, then the toggle and the size
   * through the admin settings: a failed settings write then leaves the
   * feature as it was, never on with a stale model. Leaves every cache
   * alone; the caller commits once the whole apply has succeeded, so
   * `enableReinitialize` sees the final form once instead of a mix.
   */
  const persistImageProcessing = useCallback(
    async (values: IndexSettingsFormValues): Promise<ImagePersistResult> => {
      if (!classifyChanges(values, initialFormValues).imageChanged) {
        return "skipped";
      }
      const modelId = values.image_processing_model_configuration_id;
      if (values.image_processing_enabled && modelId === null) {
        toast.error(t("toasts.captioningModelRequired"));
        return "failed";
      }
      try {
        const modelChanged =
          values.image_processing_enabled &&
          modelId !== initialFormValues.image_processing_model_configuration_id;
        if (modelChanged && modelId !== null) {
          const option = findLlmOptionById(llmProviders, modelId);
          const provider = findProviderOwningModelConfig(llmProviders, modelId);
          if (!option || !provider) {
            toast.error(t("toasts.providerResolveFailed"));
            return "failed";
          }
          const response = await fetch("/api/admin/llm/default-vision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              provider_id: provider.id,
              model_name: option.modelName,
            }),
          });
          if (!response.ok) {
            toast.error(
              await parseErrorDetail(response, t("toasts.settingsUpdateFailed"))
            );
            return "failed";
          }
        }
        const toggleOrSizeChanged =
          values.image_processing_enabled !==
            initialFormValues.image_processing_enabled ||
          values.image_processing_max_size_mb !==
            initialFormValues.image_processing_max_size_mb;
        if (toggleOrSizeChanged) {
          await saveAdminSettings({
            ...toSettings(settings),
            image_extraction_and_analysis_enabled:
              values.image_processing_enabled,
            image_analysis_max_size_mb: values.image_processing_max_size_mb,
          });
        }
        return "saved";
      } catch (error) {
        toast.error(
          error instanceof Error && error.message
            ? error.message
            : t("toasts.settingsUpdateFailed")
        );
        return "failed";
      }
    },
    [initialFormValues, llmProviders, settings, t]
  );

  /** Rebase the page onto the saved image settings, in one tick. */
  const commitImageProcessing = useCallback(
    (result: ImagePersistResult) => {
      if (result !== "saved") return;
      router.refresh();
      void mutate(SWR_KEYS.settings);
      void mutate(SWR_KEYS.llmProviders);
    },
    [router]
  );

  const applyContextualModelForward = useCallback(
    async (values: IndexSettingsFormValues): Promise<boolean> => {
      const modelConfigurationId = values.contextual_rag_model_configuration_id;
      if (!searchSettings || modelConfigurationId === null) return false;
      // Image settings first: a failed save aborts before anything else moves.
      const image = await persistImageProcessing(values);
      if (image === "failed") return false;

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
        commitImageProcessing(image);
        forwardOnlyModal.toggle(false);
        toast.success(t("toasts.contextualModelUpdated"));
        return true;
      } catch (error) {
        console.error(CONTEXTUAL_MODEL_UPDATE_LOG, error);
        toast.error(t("toasts.contextualModelUpdateFailed"));
        return false;
      }
    },
    [
      forwardOnlyModal,
      searchSettings,
      t,
      persistImageProcessing,
      commitImageProcessing,
    ]
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
        <SettingsLayouts.Header
          icon={route.icon}
          title={adminRouteTitle(route)}
        />
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
          title={adminRouteTitle(route)}
          description={t("header.description")}
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
              // Only a staged image change needs its captioning model; a
              // fresh install starts on with none, and that is not this
              // apply's business.
              if (
                classifyChanges(values, initialFormValues).imageChanged &&
                values.image_processing_enabled &&
                values.image_processing_model_configuration_id === null
              ) {
                toast.error(t("toasts.captioningModelRequired"));
                return;
              }
              const resolved = resolveModelForApply(values);
              if (!resolved) {
                toast.error(t("toasts.modelNotFound"));
                return;
              }
              // Image settings first, so the new index captions with the new
              // model from its first document. A failed save aborts here.
              const image = await persistImageProcessing(values);
              if (image === "failed") return;
              const switchoverType = toSwitchoverType(
                resolveApplyStrategy(
                  applyStrategy,
                  bannerModeFor(classifyChanges(values, initialFormValues))
                )
              );
              const response = await setNewSearchSettings({
                model: resolved.model,
                providerName: resolved.providerName,
                switchoverType,
                enableContextualRag: values.enable_contextual_rag,
                contextualRagModelConfigurationId: values.enable_contextual_rag
                  ? values.contextual_rag_model_configuration_id
                  : null,
                vectorQuantization: values.vector_quantization,
                acknowledgedWontPortCcPairIds: frozenWontPortRef.current.map(
                  (c) => c.cc_pair_id
                ),
              });

              if (!response.ok) {
                // The server's detail tells the admin the connector set drifted and to
                // reload; a generic failure would lose that.
                const detail = await response
                  .json()
                  .then((body: ErrorResponseBody) => body?.detail)
                  .catch((parseError) => {
                    console.error(
                      "Failed to parse set-new-search-settings error response",
                      parseError
                    );
                    return undefined;
                  });
                // The image save stands on the server, but no cache moves:
                // the form keeps every staged value, and re-saving the same
                // image settings on the next apply is idempotent.
                toast.error(detail || t("toasts.applyFailed"));
                return;
              }
              wontPortConsentModal.toggle(false);
              toast.success(t("toasts.reindexStarted"));
              setApplyStrategy(null);
              commitImageProcessing(image);
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
              // Block apply when Contextual Retrieval is on but no LLM is set.
              const contextualRagModelMissing =
                values.enable_contextual_rag &&
                values.contextual_rag_model_configuration_id === null;
              const changes = classifyChanges(values, initialFormValues);
              // Image processing on with no captioning model: the card warns
              // whenever it holds, but it blocks apply only while the image
              // section is what is being saved. A fresh install starts in
              // this state, and an embedding change must not be held hostage
              // to a setting it does not touch.
              const captioningModelMissing =
                values.image_processing_enabled &&
                values.image_processing_model_configuration_id === null;
              const applyBlocked =
                contextualRagModelMissing ||
                (captioningModelMissing && changes.imageChanged);
              // A change undone by hand leaves Formik dirty but stages nothing.
              const hasChanges = dirty && changes.any;
              const bannerMode = bannerModeFor(changes);
              const contextualModelOnlyChange =
                bannerMode === "contextualModelOnly";
              const imageOnlyChange = bannerMode === "imageOnly";
              const effectiveStrategy = resolveApplyStrategy(
                applyStrategy,
                bannerMode
              );
              const saveOnly = effectiveStrategy === DO_NOT_REINDEX;
              // Once something is staged the banner's copy follows the chosen
              // strategy: save-only, or any of the three that re-index.
              const strategyCopy: "doNotReindex" | "reindex" | null = hasChanges
                ? saveOnly
                  ? "doNotReindex"
                  : "reindex"
                : null;
              // Staged changes tint the banner and only the cards that hold
              // them. Do Not Re-index touches no index, so it reads as info
              // rather than as the warning the re-index strategies carry.
              const stagedVariant = saveOnly ? "info" : "warning";
              // The banner is reserved for indexing prompts: staged changes
              // and the contextual model a re-index needs. A captioning
              // model missing is a card-level setting warning, not a banner.
              const bannerActive = hasChanges || contextualRagModelMissing;
              const bannerVariant = contextualRagModelMissing
                ? "error"
                : hasChanges
                  ? stagedVariant
                  : undefined;
              const embeddingCardBorder = changes.embeddingChanged
                ? "warning"
                : undefined;
              const contextualCardBorder =
                changes.contextualToggleChanged ||
                changes.contextualModelChanged
                  ? "warning"
                  : undefined;
              const quantizationCardBorder = changes.quantizationChanged
                ? "warning"
                : undefined;
              const imageCardBorder = captioningModelMissing
                ? "warning"
                : changes.imageChanged
                  ? stagedVariant
                  : undefined;
              const wontPortConnectors = computeWontPortConnectors(
                connectorStatuses,
                toSwitchoverType(effectiveStrategy)
              );
              const reindexStrategyOptions: SelectDivider = {
                title: t("switchover.reindexOptions.label"),
                options: [
                  {
                    value: SwitchoverType.REINDEX,
                    title: t("switchover.reindexAll.label"),
                    description: markdown(
                      t("switchover.reindexAll.description")
                    ),
                    icon: SvgClock,
                  },
                  {
                    value: SwitchoverType.ACTIVE_ONLY,
                    title: t("switchover.activeOnly.label"),
                    description: markdown(
                      t("switchover.activeOnly.description")
                    ),
                    icon: SvgSlowTime,
                  },
                  {
                    value: SwitchoverType.INSTANT,
                    title: t("switchover.instant.label"),
                    description: markdown(t("switchover.instant.description")),
                    icon: SvgEmpty,
                  },
                ],
              };
              // "Do Not Re-index" exists only while Image Processing is the
              // only diff. It is absent, not disabled, everywhere else.
              const strategyOptions: SelectOptions = imageOnlyChange
                ? [
                    {
                      value: DO_NOT_REINDEX,
                      title: t("switchover.doNotReindex.label"),
                      description: markdown(
                        t("switchover.doNotReindex.description")
                      ),
                      icon: SvgCheckSquare,
                    },
                    reindexStrategyOptions,
                  ]
                : [reindexStrategyOptions];
              const switchoverStrategySelect = (
                <InputSingleSelect
                  value={effectiveStrategy}
                  defaultOption={
                    imageOnlyChange ? DO_NOT_REINDEX : SwitchoverType.REINDEX
                  }
                  onValueChange={(next) => {
                    if (isApplyStrategy(next)) setApplyStrategy(next);
                  }}
                  placeholder={t("switchover.placeholder")}
                  options={strategyOptions}
                />
              );
              const applyWithoutReindex = async () => {
                const image = await persistImageProcessing(values);
                if (image === "failed") return;
                commitImageProcessing(image);
                resetForm({ values });
                setApplyStrategy(null);
                toast.success(t("toasts.settingsUpdated"));
              };
              const revertButton = (
                <Button
                  prominence="secondary"
                  onClick={() => {
                    resetForm();
                    setApplyStrategy(null);
                  }}
                >
                  {t("actions.revert.label")}
                </Button>
              );
              const rebuildButton = (
                <Button
                  onClick={() => {
                    if (saveOnly) {
                      void applyWithoutReindex();
                      return;
                    }
                    frozenWontPortRef.current = wontPortConnectors;
                    if (wontPortConnectors.length > 0) {
                      wontPortConsentModal.toggle(true);
                    } else {
                      void submitForm();
                    }
                  }}
                  disabled={
                    applyBlocked || (!saveOnly && !connectorStatusesReady)
                  }
                  tooltip={
                    !saveOnly && !connectorStatusesReady
                      ? statusesError
                        ? t("actions.applyReindex.statusesFailed")
                        : t("actions.applyReindex.statusesLoading")
                      : undefined
                  }
                >
                  {contextualModelOnlyChange
                    ? t("actions.rebuildAll.label")
                    : saveOnly
                      ? t("actions.applyWithoutReindex.label")
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
                          disabled={applyBlocked}
                          onClick={async () => {
                            const updated =
                              await applyContextualModelForward(values);
                            if (updated) {
                              resetForm({ values });
                              setApplyStrategy(null);
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

                  <wontPortConsentModal.Provider>
                    <ConfirmationModalLayout
                      icon={SvgTrash}
                      title={t("wontPortConsentModal.title", {
                        count: frozenWontPortRef.current.length,
                      })}
                      submit={
                        <Button
                          variant="danger"
                          onClick={() => void submitForm()}
                        >
                          {t("wontPortConsentModal.submit")}
                        </Button>
                      }
                    >
                      <div className="flex flex-col gap-3">
                        <Text font="main-ui-body" color="text-03" as="p">
                          {t("wontPortConsentModal.description", {
                            count: frozenWontPortRef.current.length,
                            appName: settings.appName,
                          })}
                        </Text>
                        <div className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-08 border border-border-02 p-3">
                          {frozenWontPortRef.current.map((c) => (
                            <Text
                              key={c.cc_pair_id}
                              font="main-ui-body"
                              color="text-04"
                              as="p"
                            >
                              {t("wontPortConsentModal.connector", {
                                name: c.name,
                                status:
                                  c.cc_pair_status ===
                                  ConnectorCredentialPairStatus.INVALID
                                    ? t("wontPortConsentModal.statusInvalid")
                                    : t("wontPortConsentModal.statusPaused"),
                              })}
                            </Text>
                          ))}
                        </div>
                        <Text font="main-ui-body" color="text-03" as="p">
                          {t("wontPortConsentModal.restoreHint")}
                        </Text>
                      </div>
                    </ConfirmationModalLayout>
                  </wontPortConsentModal.Provider>

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
                        // No secondary => INSTANT backfill (new model already live):
                        // not revertible, so show progress only (no Cancel button).
                        onCancel={
                          secondarySearchSettings
                            ? () => cancelReindexModal.toggle(true)
                            : undefined
                        }
                      />
                    ) : (
                      // Non-port reindex has no PortAttempt progress → the original banner.
                      <MessageCard
                        variant="warning"
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
                    // Cloud has no re-index path, so only an image-only diff,
                    // which saves without one, gets a banner there.
                    (!NEXT_PUBLIC_CLOUD_ENABLED || imageOnlyChange) && (
                      // Active (staged or blocked), the banner pins 8px below
                      // the top so its actions stay in reach while the page
                      // scrolls, and casts a shadow while pinned.
                      <StickyBox
                        stick="top"
                        inset={2}
                        active={bannerActive}
                        shadow
                      >
                        <MessageCard
                          variant={bannerVariant}
                          title={
                            contextualRagModelMissing
                              ? t("changesBanner.contextualModelMissing.title")
                              : contextualModelOnlyChange
                                ? t("changesBanner.contextualModelOnly.title")
                                : strategyCopy === "doNotReindex"
                                  ? t("changesBanner.doNotReindex.title")
                                  : strategyCopy === "reindex"
                                    ? t("changesBanner.reindex.title")
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
                                : strategyCopy === "doNotReindex"
                                  ? t("changesBanner.doNotReindex.description")
                                  : strategyCopy === "reindex"
                                    ? t("changesBanner.reindex.description")
                                    : t("changesBanner.default.description")
                          )}
                          bottomChildren={
                            bannerActive ? (
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
                                      disabled={applyBlocked}
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
                                    wordWrap="whitespace-nowrap"
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
                                  {/* Cloud has no re-index strategies to pick. */}
                                  {!NEXT_PUBLIC_CLOUD_ENABLED && (
                                    <div className="flex-1 min-w-0">
                                      {switchoverStrategySelect}
                                    </div>
                                  )}
                                  <div className="ms-auto flex flex-row gap-2 shrink-0">
                                    {revertButton}
                                    {rebuildButton}
                                  </div>
                                </div>
                              )
                            ) : undefined
                          }
                        />
                      </StickyBox>
                    )
                  )}

                  {/* Inner Disabled/CloudDisabled wrappers AND !isReindexing so opal's
                      disabled opacity doesn't compound to 25% under this one. */}
                  <Disabled
                    disabled={isReindexing}
                    tooltip={t("reindexing.disabledTooltip")}
                  >
                    <GeneralLayouts.Section gap={6}>
                      {/* ── Embedding Model ── */}
                      <GeneralLayouts.Section
                        gap={3}
                        height="fit"
                        alignItems="stretch"
                        justifyContent="start"
                      >
                        <Content
                          title={t("embeddingModel.title")}
                          description={t("embeddingModel.description", {
                            appName: settings.appName,
                          })}
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
                                expandableContentHeight="full"
                                border="solid"
                                borderColor={embeddingCardBorder}
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
                                        description={embeddingModelDescription(
                                          findRegistryModel(
                                            currentEmbeddingModel.model_name
                                          ),
                                          t,
                                          settings.appName
                                        )}
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

                        {!NEXT_PUBLIC_CLOUD_ENABLED && (
                          <Card
                            border="solid"
                            borderColor={quantizationCardBorder}
                            rounding={4}
                          >
                            <InputHorizontal
                              title={t("vectorQuantization.title")}
                              description={t("vectorQuantization.description")}
                              withLabel
                            >
                              <InputSingleSelectField
                                name="vector_quantization"
                                defaultOption={VectorQuantization.NONE}
                                placeholder={tInputSelect(
                                  "placeholder.fallback"
                                )}
                                options={[
                                  {
                                    value: VectorQuantization.NONE,
                                    title: t("vectorQuantization.none.label"),
                                    description: t(
                                      "vectorQuantization.none.description"
                                    ),
                                  },
                                  {
                                    value: VectorQuantization.SCALAR_7_BIT,
                                    title: t(
                                      "vectorQuantization.scalar7Bit.label"
                                    ),
                                    description: t(
                                      "vectorQuantization.scalar7Bit.description"
                                    ),
                                  },
                                  {
                                    value: VectorQuantization.SCALAR_1_BIT,
                                    title: t(
                                      "vectorQuantization.scalar1Bit.label"
                                    ),
                                    description: t(
                                      "vectorQuantization.scalar1Bit.description"
                                    ),
                                  },
                                ]}
                              />
                            </InputHorizontal>
                          </Card>
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
                              <InputSwitch
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
                            borderColor={contextualCardBorder}
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
                                  <SimpleModelSelector
                                    providers={filterModelConfigurations(
                                      llmProviders ?? [],
                                      {
                                        keep: values.contextual_rag_model_configuration_id,
                                      }
                                    )}
                                    value={
                                      values.contextual_rag_model_configuration_id
                                    }
                                    disabled={!values.enable_contextual_rag}
                                    grouped={!settings.hide_provider_grouping}
                                    onChange={(modelConfigurationId) =>
                                      void setFieldValue(
                                        "contextual_rag_model_configuration_id",
                                        modelConfigurationId
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
                          <Card
                            border="solid"
                            borderColor={imageCardBorder}
                            rounding={4}
                          >
                            <GeneralLayouts.Section
                              width="full"
                              alignItems="stretch"
                            >
                              <InputHorizontal
                                title={t("imageExtraction.title")}
                                description={t("imageExtraction.description")}
                                withLabel
                              >
                                <div className="flex flex-col items-end">
                                  <SwitchField name="image_processing_enabled" />
                                  {captioningModelMissing && (
                                    <Content
                                      icon={SvgAlertTriangle}
                                      title={t(
                                        "imageProcessing.noModelSelected"
                                      )}
                                      sizePreset="secondary"
                                      variant="body"
                                      color="warning"
                                    />
                                  )}
                                </div>
                              </InputHorizontal>

                              <Disabled
                                disabled={
                                  !values.image_processing_enabled &&
                                  !isReindexing
                                }
                                tooltip={t(
                                  "imageProcessing.enableFirstTooltip"
                                )}
                              >
                                <InputHorizontal
                                  title={t("captioningModel.title")}
                                  description={t("captioningModel.description")}
                                  disabled={!values.image_processing_enabled}
                                  withLabel
                                >
                                  <SimpleModelSelector
                                    nullable
                                    providers={filterModelConfigurations(
                                      llmProviders ?? [],
                                      {
                                        imageInput: true,
                                        keep: values.image_processing_model_configuration_id,
                                      }
                                    )}
                                    value={
                                      values.image_processing_model_configuration_id
                                    }
                                    disabled={!values.image_processing_enabled}
                                    grouped={!settings.hide_provider_grouping}
                                    onChange={(modelConfigurationId) =>
                                      void setFieldValue(
                                        "image_processing_model_configuration_id",
                                        modelConfigurationId
                                      )
                                    }
                                  />
                                </InputHorizontal>
                              </Disabled>

                              <Disabled
                                disabled={
                                  !values.image_processing_enabled &&
                                  !isReindexing
                                }
                                tooltip={t(
                                  "imageProcessing.enableFirstTooltip"
                                )}
                              >
                                <InputHorizontal
                                  title={t("maxImageSize.title")}
                                  suffix={t("maxImageSize.suffix")}
                                  description={t("maxImageSize.description")}
                                  disabled={!values.image_processing_enabled}
                                  withLabel
                                >
                                  <InputSingleSelect
                                    value={String(
                                      values.image_processing_max_size_mb
                                    )}
                                    onValueChange={(value) =>
                                      void setFieldValue(
                                        "image_processing_max_size_mb",
                                        parseInt(value, 10)
                                      )
                                    }
                                    disabled={!values.image_processing_enabled}
                                    defaultOption="20"
                                    placeholder={tInputSelect(
                                      "placeholder.fallback"
                                    )}
                                    options={MAX_IMAGE_SIZE_OPTIONS.map(
                                      (size) => ({
                                        value: size,
                                        title: size,
                                      })
                                    )}
                                  />
                                </InputHorizontal>
                              </Disabled>
                            </GeneralLayouts.Section>
                          </Card>
                        </Disabled>
                      </GeneralLayouts.Section>
                    </GeneralLayouts.Section>
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
