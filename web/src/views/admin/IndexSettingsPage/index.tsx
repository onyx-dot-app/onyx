"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Formik } from "formik";
import { markdown } from "@opal/utils";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { PageLoader } from "@/refresh-components/PageLoader";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, IllustrationContent } from "@opal/layouts";
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
  type EmbeddingModelState,
  type EmbeddingProvider,
} from "@/lib/indexing/interfaces";
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
  saveAdminSettings,
  cancelNewEmbedding,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
} from "@/lib/indexing/svc";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ContentAction } from "@opal/layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useSettings } from "@/lib/settings/hooks";
import { Settings, toSettings } from "@/lib/settings/types";
import { toast } from "@/hooks/useToast";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useSecondarySearchSettings,
} from "@/lib/indexing/hooks";
import { useLlmDefaults } from "@/lib/languageModels/hooks";
import useFilter from "@/hooks/useFilter";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import type { RichStr } from "@opal/types";
import { ProviderCredentialsModal } from "@/views/admin/IndexSettingsPage/modals";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MODEL_TAB_CLOUD = "cloud-based";
const MODEL_TAB_SELF = "self-hosted";
const CLOUD_TOOLTIP = "This setting is managed by Onyx Cloud.";

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
  const isDisabled = NEXT_PUBLIC_CLOUD_ENABLED || disabled;
  const tooltip = NEXT_PUBLIC_CLOUD_ENABLED ? CLOUD_TOOLTIP : tooltipProp;

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
  if (!isCloudBased(providerName)) {
    return (
      <Content
        icon={SvgServer}
        title="Self-hosted"
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
        title="Cloud Provider"
        sizePreset="secondary"
        variant="body"
        color="muted"
        width="fit"
      />
      {provider.costslink && (
        <LinkButton href={provider.costslink} target="_blank">
          Pricing
        </LinkButton>
      )}
      {provider.docsLink && (
        <LinkButton href={provider.docsLink} target="_blank">
          Docs
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
   * Stage a model into the parent form. `customModel` is populated only when
   * the provider has no pre-registered models and the user defined the spec in
   * the connect modal (LiteLLM / Azure) — the parent uses it to set both
   * `model_name` and `custom_model`, and to remember this cloud provider as the
   * staged model's owner so submit doesn't misresolve it as self-hosted.
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
      toast.success(`Disconnected ${provider.displayName}`);
      await mutate(SWR_KEYS.embeddingProviders);
      onDeselectModel();
      disconnectModal.toggle(false);
    } catch {
      toast.error(`Failed to disconnect ${provider.displayName}`);
    }
  }, [
    isCloud,
    provider.providerName,
    provider.displayName,
    onDeselectModel,
    disconnectModal,
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
              title={`Disconnect ${provider.displayName}`}
              submit={
                <Button variant="danger" onClick={handleDisconnect}>
                  Disconnect
                </Button>
              }
            >
              <Text font="main-ui-body" color="text-03" as="p">
                {markdown(
                  `This will disconnect all embedding models from provider **${provider.displayName}**.`
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

      <GeneralLayouts.Section gap={0.25}>
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
                suffix={provider.deprecated ? "(deprecated)" : undefined}
                sizePreset="secondary"
              />

              {isCloud && isConfigured ? (
                <GeneralLayouts.Section
                  flexDirection="row"
                  gap={0.25}
                  width="fit"
                >
                  <Button
                    icon={SvgUnplug}
                    prominence="tertiary"
                    size="sm"
                    disabled={providerGroupContainsCurrentModelName}
                    tooltip={
                      providerGroupContainsCurrentModelName
                        ? "Cannot disconnect this embedding model because it is the current default. Select a new one before proceeding."
                        : undefined
                    }
                    onClick={() => disconnectModal.toggle(true)}
                  />
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    size="sm"
                    aria-label="Edit credentials"
                    tooltip="Edit credentials"
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
            rounding="md"
            padding="sm"
            onClick={() => providerCreationModal.toggle(true)}
          >
            <ContentAction
              title={`Add configs for your ${provider.displayName} embedding providers.`}
              sizePreset="secondary"
              variant="body"
              color="muted"
              padding="md"
              rightChildren={
                <Button
                  prominence="tertiary"
                  rightIcon={SvgPlusCircle}
                  onClick={() => providerCreationModal.toggle(true)}
                >
                  Add Configuration
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
                ? "This embedding model is deprecated and cannot be connected to."
                : undefined
            }
          >
            Connect
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
                ? "This embedding model is deprecated and cannot be selected."
                : undefined
            }
          >
            Select Model
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
            Current Model
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
            Selected
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
      rounding="md"
      padding="xs"
      onClick={isClickable ? onSelect : undefined}
    >
      <GeneralLayouts.Section flexDirection="row" alignItems="start">
        <GeneralLayouts.Section gap={0} padding={0.5} alignItems="start">
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

interface IndexSettingsFormValues {
  model_name: string;
  /**
   * Populated when the staged model came from the "Add Custom Model" modal
   * — i.e. it's not in `CLOUD_BASED_PROVIDERS` / `SELF_HOSTED_PROVIDERS`.
   * The submit path uses this directly instead of looking the name up in
   * the static registry. Cleared whenever the user selects a registered
   * model.
   */
  custom_model: EmbeddingModel | null;
  /**
   * The cloud provider that owns a staged `custom_model` (LiteLLM / Azure).
   * Those providers have no pre-registered models, so `resolveProviderName`
   * can't recover their identity from the model name alone and would fall
   * through to `CUSTOM` (self-hosted) — sending `provider_type=null` to the
   * backend and bypassing the cloud credentials. Carrying it explicitly keeps
   * the staged model bound to its provider. `null` for registered or
   * self-hosted models, where name-based resolution is sufficient.
   */
  custom_model_provider: EmbeddingProviderName | null;
  enable_contextual_rag: boolean;
  contextual_rag_model_configuration_id: number | null;
}

export default function IndexSettingsPage() {
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
        toast.success("Settings updated");
      } catch {
        toast.error("Failed to update settings");
      }
    },
    [settings, router]
  );

  const imageProcessingEnabled =
    settings.image_extraction_and_analysis_enabled ?? false;

  const { data: secondarySearchSettings } = useSecondarySearchSettings();
  const isReindexing = !!secondarySearchSettings;

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
        toast.error("Could not resolve provider");
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
            (await response.json()).detail ?? "Failed to update captioning LLM"
          );
        }
        await mutate(SWR_KEYS.llmProviders);
        toast.success("Captioning LLM updated");
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "An unknown error occurred"
        );
      }
    },
    [llmProviders]
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

  const initialFormValues: IndexSettingsFormValues = useMemo(
    () => ({
      model_name: currentEmbeddingModel?.model_name ?? "",
      custom_model: null,
      custom_model_provider: null,
      enable_contextual_rag: searchSettings?.enable_contextual_rag ?? false,
      contextual_rag_model_configuration_id:
        searchSettings?.contextual_rag_model_configuration_id ?? null,
    }),
    [currentEmbeddingModel, searchSettings]
  );

  const handleCancelReindex = useCallback(async () => {
    const response = await cancelNewEmbedding();
    if (!response.ok) {
      toast.error("Failed to cancel re-indexing");
      return;
    }
    cancelReindexModal.toggle(false);
    toast.success("Re-indexing canceled");
    await Promise.all([
      mutate(SWR_KEYS.currentSearchSettings),
      mutate(SWR_KEYS.secondarySearchSettings),
      mutate(SWR_KEYS.indexingStatus),
    ]);
  }, [cancelReindexModal]);

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
          title="Cancel Re-index"
          submit={
            <Button variant="danger" onClick={handleCancelReindex}>
              Cancel
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03" as="p">
            Cancelling will revert to the previous embedding model and all
            re-indexing progress will be lost.
          </Text>
        </ConfirmationModalLayout>
      </cancelReindexModal.Provider>

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="Configure how documents are indexed, embedded, and prepared for search and retrieval."
          divider
        />

        <SettingsLayouts.Body>
          <Formik<IndexSettingsFormValues>
            enableReinitialize
            initialValues={initialFormValues}
            onSubmit={async (values) => {
              // Custom self-hosted models live outside the static registry,
              // so the form carries their spec (`modelDim`, `normalize`, etc.)
              // in `custom_model` for submission. The provider, however, is
              // ALWAYS resolved through `resolveProviderName` — see its NOTE
              // for why this is the single source of truth for provider
              // discrimination.
              const stagedModel =
                values.custom_model ?? findRegistryModel(values.model_name);
              if (!stagedModel) {
                toast.error("Could not find the selected model");
                return;
              }
              // A staged custom model from a no-registry cloud provider
              // (LiteLLM / Azure) carries its owning provider explicitly;
              // otherwise fall back to resolving the provider from the model
              // name against the static registry.
              const providerName =
                values.custom_model_provider ??
                resolveProviderName(values.model_name, null);

              const response = await setNewSearchSettings({
                model: stagedModel,
                providerName,
                switchoverType,
                enableContextualRag: values.enable_contextual_rag,
                contextualRagModelConfigurationId: values.enable_contextual_rag
                  ? values.contextual_rag_model_configuration_id
                  : null,
              });

              if (!response.ok) {
                toast.error("Failed to apply settings");
                return;
              }

              toast.success("Re-indexing started");
              setSwitchoverType(SwitchoverType.REINDEX);
              await Promise.all([
                mutate(SWR_KEYS.currentSearchSettings),
                mutate(SWR_KEYS.secondarySearchSettings),
              ]);
            }}
          >
            {({ values, dirty, setFieldValue, resetForm, submitForm }) => {
              const isModelStaged =
                values.model_name !== initialFormValues.model_name &&
                !!values.model_name;
              const stagedModelName = isModelStaged ? values.model_name : null;
              const statusVariant = dirty ? "warning" : undefined;

              return (
                <>
                  <customModelModal.Provider>
                    <ProviderCredentialsModal
                      provider={CUSTOM_PROVIDER}
                      existingModel={
                        currentProviderName === EmbeddingProviderName.CUSTOM
                          ? (currentEmbeddingModelSpec ?? undefined)
                          : undefined
                      }
                      onSubmit={(customModel) => {
                        if (customModel) {
                          void setFieldValue(
                            "model_name",
                            customModel.modelName
                          );
                          void setFieldValue("custom_model", customModel);
                          // Self-hosted custom models resolve to CUSTOM by
                          // name — no cloud provider to bind.
                          void setFieldValue("custom_model_provider", null);
                        }
                        customModelModal.toggle(false);
                      }}
                    />
                  </customModelModal.Provider>

                  {isReindexing ? (
                    <MessageCard
                      variant="warning"
                      headerPadding="sm"
                      title="Re-indexing in progress"
                      description={markdown(
                        `Switching to **${secondarySearchSettings?.model_name}**. Existing documents are being re-embedded — this may take hours or days depending on corpus size. The previous model continues to serve queries until the switchover completes.`
                      )}
                      bottomChildren={
                        <GeneralLayouts.Section
                          flexDirection="row"
                          gap={0.5}
                          justifyContent="end"
                          padding={0.5}
                        >
                          <Button
                            icon={SvgExternalLink}
                            href="/admin/indexing/status"
                          >
                            See Connectors
                          </Button>
                          <Button
                            variant="danger"
                            prominence="secondary"
                            onClick={() => cancelReindexModal.toggle(true)}
                          >
                            Cancel Re-index
                          </Button>
                        </GeneralLayouts.Section>
                      }
                    />
                  ) : (
                    !NEXT_PUBLIC_CLOUD_ENABLED && (
                      <MessageCard
                        variant={statusVariant}
                        headerPadding="sm"
                        title="Changes require a full re-index."
                        description={markdown(
                          "Modifying embedding or retrieval settings requires a full re-index of all documents to take effect, which may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
                        )}
                        bottomChildren={
                          dirty ? (
                            <div className="flex flex-row items-end gap-4 p-2">
                              <div className="flex-1 min-w-0">
                                <InputSelect
                                  value={switchoverType}
                                  onValueChange={(v) =>
                                    setSwitchoverType(v as SwitchoverType)
                                  }
                                >
                                  <InputSelect.Trigger placeholder="Select a switchover strategy" />
                                  <InputSelect.Content>
                                    <InputSelect.Item
                                      value={SwitchoverType.REINDEX}
                                      icon={SvgClock}
                                      wrapDescription
                                      description="Safest option. Continue using the current document index with existing settings until all connectors have completed a successful index attempt."
                                    >
                                      Re-index All Connectors Then Switch
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={SwitchoverType.ACTIVE_ONLY}
                                      icon={SvgSlowTime}
                                      wrapDescription
                                      description="Continue using the current document index with existing settings until all active (not paused/deleting) connectors have completed a successful index attempt."
                                    >
                                      Re-index Active Connectors Then Switch
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={SwitchoverType.INSTANT}
                                      icon={SvgEmpty}
                                      wrapDescription
                                      description="Immediately clear the current document index and switch to the new settings. Requires re-indexing all connectors before the index is repopulated for search."
                                    >
                                      Switch Before Re-index
                                    </InputSelect.Item>
                                  </InputSelect.Content>
                                </InputSelect>
                              </div>
                              <div className="flex flex-row gap-2 shrink-0">
                                <Button
                                  prominence="secondary"
                                  onClick={() => {
                                    resetForm();
                                    setSwitchoverType(SwitchoverType.REINDEX);
                                  }}
                                >
                                  Revert
                                </Button>
                                <Button onClick={() => void submitForm()}>
                                  Apply & Re-index
                                </Button>
                              </div>
                            </div>
                          ) : undefined
                        }
                      />
                    )
                  )}

                  {/* ── Embedding Model ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="Embedding Model"
                      description="Onyx uses this model to encode documents for search and retrieval."
                      sizePreset="main-content"
                      variant="section"
                    />

                    {NEXT_PUBLIC_CLOUD_ENABLED ? (
                      <CloudDisabled>
                        <Card border="solid" rounding="lg" padding="sm">
                          <GeneralLayouts.Section padding={0.5}>
                            <Content
                              icon={SvgVector}
                              title="Embedding model and settings are managed by Onyx Cloud."
                              sizePreset="main-ui"
                              variant="section"
                            />
                          </GeneralLayouts.Section>
                        </Card>
                      </CloudDisabled>
                    ) : (
                      currentEmbeddingModel && (
                        <Disabled
                          disabled={isReindexing}
                          tooltip="Cancel the in-progress re-index to switch models."
                        >
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
                              rounding="lg"
                              padding={viewAllModelsOpen ? "fit" : "sm"}
                              expandedContent={
                                <>
                                  <Tabs.Content value={MODEL_TAB_CLOUD}>
                                    {filteredCloudProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
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
                                              ) => {
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  customModel ?? null
                                                );
                                                // Bind a just-defined LiteLLM /
                                                // Azure model to its provider so
                                                // submit doesn't misresolve it.
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  customModel
                                                    ? provider.providerName
                                                    : null
                                                );
                                              }}
                                              onDeselectModel={() => {
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                            />
                                          )
                                        )}
                                      </GeneralLayouts.Section>
                                    ) : (
                                      <IllustrationContent
                                        illustration={SvgNoResult}
                                        title="No cloud-based models found"
                                        description="Try a different search term."
                                      />
                                    )}
                                  </Tabs.Content>

                                  <Tabs.Content value={MODEL_TAB_SELF}>
                                    {filteredSelfHostedProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
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
                                              onSelectModel={(name) => {
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                              onDeselectModel={() => {
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                            />
                                          )
                                        )}

                                        <GeneralLayouts.Section gap={0.25}>
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
                                                  title="Custom Models"
                                                  sizePreset="secondary"
                                                />
                                              </div>
                                            </GeneralLayouts.Section>
                                          </div>

                                          <SelectCard
                                            state="filled"
                                            rounding="md"
                                            padding="sm"
                                            onClick={() =>
                                              customModelModal.toggle(true)
                                            }
                                          >
                                            <ContentAction
                                              title="Set up a custom embedding model."
                                              sizePreset="secondary"
                                              variant="body"
                                              color="muted"
                                              padding="md"
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
                                                  Add Custom Model
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
                                        title="No self-hosted models found"
                                        description="Try a different search term."
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
                                      placeholder="Search models..."
                                      variant="internal"
                                      searchIcon
                                      value={query}
                                      onChange={(e) => setQuery(e.target.value)}
                                    />
                                    <div className="flex flex-row">
                                      {isModelStaged && (
                                        <Button
                                          icon={SvgRevert}
                                          prominence="internal"
                                          tooltip="Revert embedding model selection"
                                          onClick={() => {
                                            void setFieldValue(
                                              "model_name",
                                              initialFormValues.model_name
                                            );
                                            void setFieldValue(
                                              "custom_model",
                                              null
                                            );
                                            void setFieldValue(
                                              "custom_model_provider",
                                              null
                                            );
                                          }}
                                        />
                                      )}
                                      <Button
                                        prominence="internal"
                                        onClick={() =>
                                          setViewAllModelsOpen(false)
                                        }
                                        rightIcon={SvgFold}
                                      >
                                        Fold Models
                                      </Button>
                                    </div>
                                  </div>

                                  <div className="px-2">
                                    <Tabs.List>
                                      <Tabs.Trigger value={MODEL_TAB_CLOUD}>
                                        Cloud-based
                                      </Tabs.Trigger>
                                      <Tabs.Trigger value={MODEL_TAB_SELF}>
                                        Self-hosted
                                      </Tabs.Trigger>
                                    </Tabs.List>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex flex-row items-start w-full">
                                  <GeneralLayouts.Section
                                    padding={0.5}
                                    gap={0}
                                    alignItems="start"
                                  >
                                    <Content
                                      icon={currentProvider?.icon ?? SvgServer}
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
                                                m.modelName === stagedModelName
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
                                      View All Models
                                    </Button>
                                    {isCurrentCloudBased && (
                                      <div className="p-1">
                                        <Button
                                          icon={SvgSettings}
                                          prominence="tertiary"
                                          size="md"
                                          onClick={() => editModal.toggle(true)}
                                        />
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </Card>
                          </Tabs>
                        </Disabled>
                      )
                    )}
                  </GeneralLayouts.Section>

                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  {/* ── Retrieval Optimization ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="Retrieval Optimization"
                      description="Additional indexing features that improve search accuracy by configuring how documents are chunked and contextualized. These can increase embedding cost."
                      sizePreset="main-content"
                      variant="section"
                    />

                    <CloudDisabled
                      disabled
                      tooltip="Multipass Indexing is disabled temporarily and will be available in the future."
                    >
                      <Card border="solid" rounding="lg">
                        <InputHorizontal
                          title="Multipass Indexing"
                          description="Index documents as chunks of varying sizes to better identify relevant sources."
                          tag={{
                            title: "temporarily unavailable",
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
                      disabled={isReindexing || !hasAnyLlm}
                      tooltip={
                        isReindexing
                          ? "Cancel the in-progress re-index to change retrieval settings."
                          : !hasAnyLlm
                            ? markdown(
                                "Contextual Retrieval is disabled because you have no models configured. Set up a [Language Model](/admin/configuration/language-models) first."
                              )
                            : undefined
                      }
                    >
                      <Card
                        border="solid"
                        borderColor={statusVariant}
                        rounding="lg"
                      >
                        <GeneralLayouts.Section
                          width="full"
                          alignItems="stretch"
                        >
                          <InputHorizontal
                            title="Contextual Retrieval"
                            description="Add document-level context to every indexed chunk to improve hybrid search relevance. This can increase embedding cost significantly."
                            withLabel
                          >
                            <SwitchField name="enable_contextual_rag" />
                          </InputHorizontal>

                          <Disabled
                            disabled={!values.enable_contextual_rag}
                            tooltip="Cannot modify while Contextual Retrieval is off."
                          >
                            <InputHorizontal
                              title="Contextual Retrieval LLM"
                              description="This model will be used to generate context for chunks."
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

                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  {/* ── Image Processing ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="Image Processing"
                      description="Use LLM model to analyze and add descriptions to images during indexing."
                      sizePreset="main-content"
                      variant="section"
                    />

                    <Disabled
                      disabled={!hasAnyVisionLlm}
                      tooltip={
                        !hasAnyVisionLlm
                          ? markdown(
                              "Image Processing is disabled because you have no vision-capable models configured. Set up a vision-capable [Language Model](/admin/configuration/language-models) first."
                            )
                          : undefined
                      }
                    >
                      <Card border="solid" rounding="lg">
                        <GeneralLayouts.Section
                          width="full"
                          alignItems="stretch"
                        >
                          <InputHorizontal
                            title="Extract & Caption Images"
                            description="Extract embedded images from uploaded files (PDFs, DOCX, etc.) and summarize them with a vision-capable LLM so image-only documents become searchable and answerable. Requires a vision-capable default LLM."
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
                            disabled={!imageProcessingEnabled}
                            tooltip="Enable Extract & Caption Images to configure this."
                          >
                            <InputHorizontal
                              title="Captioning LLM"
                              description="This model will be used to analyze images during indexing. Only vision-capable models can be selected. Updates apply to documents indexed going forward — existing captions are baked into prior embeddings."
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
                            disabled={!imageProcessingEnabled}
                            tooltip="Enable Extract & Caption Images to configure this."
                          >
                            <InputHorizontal
                              title="Max Image Size for Analysis"
                              suffix="(MB)"
                              description="Images above this size will be skipped to limit resource usage."
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
                                    <InputSelect.Item key={size} value={size}>
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
                </>
              );
            }}
          </Formik>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </>
  );
}
