"use client";

import { useCallback, useMemo, useState } from "react";
import { Formik } from "formik";
import { markdown } from "@opal/utils";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import {
  Button,
  Card,
  Divider,
  LinkButton,
  MessageCard,
  SelectCard,
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
  SvgNoImage,
  SvgPlusCircle,
  SvgRevert,
  SvgServer,
  SvgSettings,
  SvgSlowTime,
  SvgUnplug,
  SvgVector,
} from "@opal/icons";
import Switch from "@/refresh-components/inputs/Switch";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import {
  EmbeddingProviderName,
  SwitchoverType,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingModelState,
  type EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import {
  CLOUD_BASED_PROVIDERS,
  SELF_HOSTED_PROVIDERS,
  findCloudProvider,
  getCurrentModelCopy,
  getEmbeddingProvider,
  MAX_IMAGE_SIZE_OPTIONS,
} from "@/lib/indexing";
import Tabs from "@/refresh-components/Tabs";
import {
  saveAdminSettings,
  cancelNewEmbedding,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
} from "@/lib/indexing/svc";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ContentAction } from "@opal/layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useLLMContextualCosts,
  useSecondarySearchSettings,
} from "@/hooks/useSearchSettings";
import Spacer from "@/refresh-components/Spacer";
import useFilter from "@/hooks/useFilter";
import { ProviderCredentialsModal } from "@/refresh-pages/admin/IndexSettingsPage/modals";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MODEL_TAB_CLOUD = "cloud-based";
const MODEL_TAB_SELF = "self-hosted";
const SWITCHOVER_NONE = "none";
const SELECT_CARD_STATE: Record<
  EmbeddingModelState,
  "empty" | "filled" | "selected"
> = {
  unconnected: "filled",
  connected: "filled",
  current: "filled",
  selected: "selected",
};
const CLOUD_TOOLTIP = "This setting is managed by Onyx Cloud.";

/**
 * Wrapper that disables its children when either:
 * 1. The app is running on Onyx Cloud (`NEXT_PUBLIC_CLOUD_ENABLED`), or
 * 2. A local `disabled` condition is true (e.g. a parent toggle is off).
 */
interface CloudDisabledProps {
  disabled?: boolean;
  tooltip?: string;
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
  providerType: EmbeddingProviderName | null;
}

function EmbeddingProviderInfo({ providerType }: EmbeddingProviderInfoProps) {
  if (!providerType) {
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

  const cloudProvider = findCloudProvider(providerType);
  if (!cloudProvider) return null;

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
      {cloudProvider.costslink && (
        <LinkButton href={cloudProvider.costslink} target="_blank">
          Pricing
        </LinkButton>
      )}
      {cloudProvider.docsLink && (
        <LinkButton href={cloudProvider.docsLink} target="_blank">
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
  models: EmbeddingModel[];
  currentModelName?: string;
  selectedModelName?: string;
  isCloud?: boolean;
  existingCredentials?: ConfiguredEmbeddingProvider;
  onSelectModel: (modelName: string) => void;
  onDeselectModel: () => void;
}

function ProviderGroup({
  provider,
  models,
  currentModelName,
  selectedModelName,
  isCloud = false,
  existingCredentials,
  onSelectModel,
  onDeselectModel,
}: ProviderGroupProps) {
  const isConfigured = isCloud ? !!existingCredentials : true;
  const disconnectModal = useCreateModal();
  const connectModal = useCreateModal();
  const editCredentialsModal = useCreateModal();
  const providerCreationModal = useCreateModal();
  const [pendingModel, setPendingModel] = useState<EmbeddingModel | null>(null);

  const handleDisconnect = useCallback(async () => {
    if (!isCloud) return;
    try {
      await disconnectEmbeddingProvider(provider.providerName);
      toast.success(`Disconnected ${provider.displayName}`);
      await mutate(SWR_KEYS.embeddingProviders);
      disconnectModal.toggle(false);
    } catch {
      toast.error(`Failed to disconnect ${provider.displayName}`);
    }
  }, [isCloud, provider.providerName, name, disconnectModal]);

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
        setPendingModel(model);
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
    ]
  );

  return (
    <>
      {isCloud && (
        <>
          <disconnectModal.Provider>
            <ConfirmationModalLayout
              icon={SvgUnplug}
              title={`Disconnect ${name}`}
              submit={
                <Button variant="danger" onClick={handleDisconnect}>
                  Disconnect
                </Button>
              }
            >
              <Text font="main-ui-body" color="text-03" as="p">
                {markdown(
                  `This will disconnect all embedding models from provider **${name}**.`
                )}
              </Text>
            </ConfirmationModalLayout>
          </disconnectModal.Provider>

          <connectModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              onSubmit={async () => {
                await mutate(SWR_KEYS.embeddingProviders);
                connectModal.toggle(false);
                if (pendingModel) {
                  onSelectModel(pendingModel.modelName);
                  setPendingModel(null);
                }
              }}
              onCancel={() => {
                connectModal.toggle(false);
                setPendingModel(null);
              }}
            />
          </connectModal.Provider>

          <editCredentialsModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              existingCredentials={existingCredentials}
              onSubmit={async () => {
                await mutate(SWR_KEYS.embeddingProviders);
                editCredentialsModal.toggle(false);
              }}
              onCancel={() => editCredentialsModal.toggle(false)}
            />
          </editCredentialsModal.Provider>
        </>
      )}

      <providerCreationModal.Provider>
        <ProviderCredentialsModal
          provider={provider}
          onSubmit={async () => {
            await mutate(SWR_KEYS.embeddingProviders);
            providerCreationModal.toggle(false);
          }}
          onCancel={() => providerCreationModal.toggle(false)}
        />
      </providerCreationModal.Provider>

      <GeneralLayouts.Section gap={0.25}>
        <div className="px-1 pt-1 w-full h-[var(--opal-line-height-lg)]">
          <GeneralLayouts.Section flexDirection="row" gap={0}>
            <Spacer horizontal rem={0.675} />
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
                    disabled={models.some(
                      (m) => m.modelName === currentModelName
                    )}
                    onClick={() => disconnectModal.toggle(true)}
                  />
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    size="sm"
                    onClick={() => editCredentialsModal.toggle(true)}
                  />
                  <Spacer horizontal rem={0.25} />
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
          models.map((model) => (
            <EmbeddingModelCard
              key={model.modelName}
              model={model}
              provider={provider}
              modelState={getModelState(model)}
              deprecated={provider.deprecated}
              onSelect={() => handleModelSelect(model)}
            />
          ))
        )}
      </GeneralLayouts.Section>
    </>
  );
}

interface EmbeddingModelCardProps {
  provider: EmbeddingProvider;
  model: EmbeddingModel;
  modelState: EmbeddingModelState;
  deprecated?: boolean;
  onSelect?: () => void;
}

function EmbeddingModelCard({
  provider,
  model,
  modelState,
  deprecated,
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
            disabled={deprecated}
            tooltip={
              deprecated
                ? "This embedding model is deprecated and cannot be selected."
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
            disabled={deprecated}
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
    !deprecated &&
    (modelState === "unconnected" ||
      modelState === "connected" ||
      modelState === "current" ||
      modelState === "selected");

  return (
    <SelectCard
      state={SELECT_CARD_STATE[modelState]}
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
            <EmbeddingProviderInfo providerType={provider.providerName} />
          </div>
        </GeneralLayouts.Section>
        {topRightButton && <div className="shrink-0">{topRightButton}</div>}
      </GeneralLayouts.Section>
    </SelectCard>
  );
}

interface IndexSettingsFormValues {
  model_name: string;
  enable_contextual_rag: boolean;
  contextual_rag_llm_name: string | null;
  contextual_rag_llm_provider: string | null;
}

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const editModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState(MODEL_TAB_CLOUD);
  const [switchoverType, setSwitchoverType] = useState<
    SwitchoverType | typeof SWITCHOVER_NONE
  >(SWITCHOVER_NONE);

  const configOnlyProviders = useMemo(
    () => CLOUD_BASED_PROVIDERS.filter((p) => p.embeddingModels.length === 0),
    []
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
      const cloudBasedMap = new Map<string, EmbeddingModel[]>();
      const selfHostedMap = new Map<string, EmbeddingModel[]>();

      for (const provider of filteredProviders) {
        const isCloud = CLOUD_BASED_PROVIDERS.includes(provider);
        const map = isCloud ? cloudBasedMap : selfHostedMap;
        const key = provider.providerName;
        if (!map.has(key)) map.set(key, []);
        map.set(key, provider.embeddingModels);
      }

      const toGroups = (
        providers: EmbeddingProvider[],
        map: Map<string, EmbeddingModel[]>
      ) =>
        providers
          .filter((p) => map.has(p.providerName))
          .map((p) => ({ provider: p, models: map.get(p.providerName)! }));

      return {
        filteredCloudProviders: toGroups(CLOUD_BASED_PROVIDERS, cloudBasedMap),
        filteredSelfHostedProviders: toGroups(
          SELF_HOSTED_PROVIDERS,
          selfHostedMap
        ),
      };
    }, [filteredProviders]);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      if (!settings.settings) return;

      try {
        await saveAdminSettings({ ...settings.settings, ...updates });
        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success("Settings updated");
      } catch {
        toast.error("Failed to update settings");
      }
    },
    [settings.settings, router]
  );

  const imageProcessingEnabled =
    settings.settings.image_extraction_and_analysis_enabled ?? false;

  const { data: currentEmbeddingModel, isLoading: isLoadingCurrentModel } =
    useCurrentEmbeddingModel();

  const currentCloudProvider = findCloudProvider(
    currentEmbeddingModel?.provider_type ?? null
  );

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useCurrentSearchSettings();
  const { data: contextualCosts } = useLLMContextualCosts();
  const { data: configuredProviders } = useConfiguredEmbeddingProviders();
  const { data: secondarySearchSettings } = useSecondarySearchSettings();
  const isReindexing = !!secondarySearchSettings;
  const cancelReindexModal = useCreateModal();

  const initialFormValues: IndexSettingsFormValues = useMemo(
    () => ({
      model_name: currentEmbeddingModel?.model_name ?? "",
      enable_contextual_rag: searchSettings?.enable_contextual_rag ?? false,
      contextual_rag_llm_name: searchSettings?.contextual_rag_llm_name ?? null,
      contextual_rag_llm_provider:
        searchSettings?.contextual_rag_llm_provider ?? null,
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
      mutate(SWR_KEYS.secondarySearchSettings),
      mutate(SWR_KEYS.indexingStatus),
    ]);
  }, [cancelReindexModal]);

  if (isLoadingCurrentModel || isLoadingSearchSettings) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <>
      {currentCloudProvider && (
        <editModal.Provider>
          <ProviderCredentialsModal
            provider={currentCloudProvider}
            existingCredentials={configuredProviders?.get(
              currentCloudProvider.providerName
            )}
            onSubmit={async () => {
              await mutate(SWR_KEYS.embeddingProviders);
              editModal.toggle(false);
            }}
            onCancel={() => editModal.toggle(false)}
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
            onSubmit={async (values, { resetForm }) => {
              const result = getCurrentModelCopy(values.model_name);
              if (!result) {
                toast.error("Could not find the selected model");
                return;
              }

              if (switchoverType === SWITCHOVER_NONE) {
                toast.success("Settings applied");
                resetForm({ values });
                setSwitchoverType(SWITCHOVER_NONE);
                return;
              }

              const response = await setNewSearchSettings({
                model: result.model,
                providerName: result.providerName,
                switchoverType: switchoverType as SwitchoverType,
                enableContextualRag: values.enable_contextual_rag,
                contextualRagLlmName: values.contextual_rag_llm_name,
                contextualRagLlmProvider: values.contextual_rag_llm_provider,
              });

              if (!response.ok) {
                toast.error("Failed to apply settings");
                return;
              }

              toast.success("Re-indexing started");
              resetForm({ values });
              setSwitchoverType(SWITCHOVER_NONE);
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
              const statusVariant = dirty
                ? switchoverType === SWITCHOVER_NONE
                  ? "info"
                  : "warning"
                : undefined;

              return (
                <>
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
                        title={
                          statusVariant === "info"
                            ? "Changes apply to newly indexed content only."
                            : "Changes require a full re-index."
                        }
                        description={markdown(
                          statusVariant === "info"
                            ? "Selected changes will take effect only for documents indexed going forward. Existing documents will not be updated unless you run a full re-index.\nRe-indexing may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
                            : "Modifying embedding or retrieval settings requires a full re-index of all documents to take effect, which may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
                        )}
                        bottomChildren={
                          dirty ? (
                            <div className="flex flex-row items-end gap-4 p-2">
                              <div className="flex-1 min-w-0">
                                <InputSelect
                                  value={switchoverType}
                                  onValueChange={(v) =>
                                    setSwitchoverType(
                                      v as
                                        | SwitchoverType
                                        | typeof SWITCHOVER_NONE
                                    )
                                  }
                                >
                                  <InputSelect.Trigger placeholder="Select a switchover strategy" />
                                  <InputSelect.Content>
                                    <InputSelect.Item
                                      value={SWITCHOVER_NONE}
                                      icon={SvgNoImage}
                                      wrapDescription
                                      description="Safe option. Only apply changes to newly indexed content."
                                    >
                                      Do Not Re-index
                                    </InputSelect.Item>
                                    <Divider title="Re-index Options" />
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
                                    setSwitchoverType(SWITCHOVER_NONE);
                                  }}
                                >
                                  Revert
                                </Button>
                                <Button onClick={() => void submitForm()}>
                                  {switchoverType === SWITCHOVER_NONE
                                    ? "Apply without Re-index"
                                    : "Apply & Re-index"}
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
                    ) : (
                      currentEmbeddingModel && (
                        <Disabled
                          disabled={isReindexing}
                          tooltip="Cancel the in-progress re-index to switch models."
                        >
                          <Tabs
                            value={activeModelTab}
                            onValueChange={setActiveModelTab}
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
                                  <Tabs.Content
                                    value={MODEL_TAB_CLOUD}
                                    className="pt-0"
                                  >
                                    {filteredCloudProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
                                      >
                                        {filteredCloudProviders.map(
                                          ({ provider, models }) => (
                                            <ProviderGroup
                                              key={provider.providerName}
                                              provider={provider}
                                              models={models}
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
                                              onSelectModel={(name) =>
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                )
                                              }
                                              onDeselectModel={() =>
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                )
                                              }
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

                                  <Tabs.Content
                                    value={MODEL_TAB_SELF}
                                    className="pt-0"
                                  >
                                    {filteredSelfHostedProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
                                      >
                                        {filteredSelfHostedProviders.map(
                                          ({
                                            provider: shProvider,
                                            models,
                                          }) => (
                                            <ProviderGroup
                                              key={shProvider.providerName}
                                              provider={shProvider}
                                              models={models}
                                              currentModelName={
                                                currentEmbeddingModel?.model_name
                                              }
                                              selectedModelName={
                                                stagedModelName ?? undefined
                                              }
                                              onSelectModel={(name) =>
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                )
                                              }
                                              onDeselectModel={() =>
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                )
                                              }
                                            />
                                          )
                                        )}
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
                                      leftSearchIcon
                                      value={query}
                                      onChange={(e) => setQuery(e.target.value)}
                                    />
                                    <div className="flex flex-row">
                                      {dirty && (
                                        <Button
                                          icon={SvgRevert}
                                          prominence="internal"
                                          onClick={() => {
                                            resetForm();
                                            setSwitchoverType(SWITCHOVER_NONE);
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
                                    <Tabs.List variant="underline">
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
                                      icon={
                                        getEmbeddingProvider(
                                          currentEmbeddingModel.model_name
                                        ).icon
                                      }
                                      title={currentEmbeddingModel.model_name}
                                      description={
                                        getCurrentModelCopy(
                                          currentEmbeddingModel.model_name
                                        )?.model.description
                                      }
                                      sizePreset="main-ui"
                                      variant="section"
                                    />
                                    <div className="flex flex-row items-center gap-2 pt-2 px-6">
                                      <EmbeddingProviderInfo
                                        providerType={
                                          currentEmbeddingModel.provider_type
                                        }
                                      />
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
                                    {currentCloudProvider && (
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
                      disabled={isReindexing}
                      tooltip={
                        isReindexing
                          ? "Cancel the in-progress re-index to change retrieval settings."
                          : undefined
                      }
                    >
                      <Card
                        border="solid"
                        borderColor={statusVariant}
                        rounding="lg"
                      >
                        <GeneralLayouts.Section width="full">
                          <InputHorizontal
                            title="Contextual Retrieval"
                            description="Add document-level context to every indexed chunk to improve hybrid search relevance. This can increase embedding cost significantly."
                            withLabel
                          >
                            <Switch
                              checked={values.enable_contextual_rag}
                              onCheckedChange={(checked) => {
                                void setFieldValue(
                                  "enable_contextual_rag",
                                  checked
                                );
                              }}
                            />
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
                              <InputSelect
                                value={values.contextual_rag_llm_name ?? ""}
                                onValueChange={(value) => {
                                  const selected = contextualCosts?.find(
                                    (cost) => cost.model_name === value
                                  );
                                  void setFieldValue(
                                    "contextual_rag_llm_name",
                                    value
                                  );
                                  void setFieldValue(
                                    "contextual_rag_llm_provider",
                                    selected?.provider ?? null
                                  );
                                }}
                                disabled={!values.enable_contextual_rag}
                              >
                                <InputSelect.Trigger placeholder="Select a model" />
                                <InputSelect.Content>
                                  {(contextualCosts ?? []).map((cost) => (
                                    <InputSelect.Item
                                      key={cost.model_name}
                                      value={cost.model_name}
                                    >
                                      {cost.model_name}
                                    </InputSelect.Item>
                                  ))}
                                </InputSelect.Content>
                              </InputSelect>
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

                    <CloudDisabled>
                      <Card border="solid" rounding="lg">
                        <GeneralLayouts.Section width="full">
                          <InputHorizontal
                            title="Extract & Caption Images"
                            description="Extract images during document indexing and generate searchable descriptions."
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

                          <Disabled disabled={!imageProcessingEnabled}>
                            <InputHorizontal
                              title="Captioning LLM"
                              description="This model will be used to analyze images during indexing."
                              disabled={!imageProcessingEnabled}
                              withLabel
                            >
                              {/* TODO(@raunakab): wire up */}
                              <InputSelect
                                value=""
                                onValueChange={() => {}}
                                disabled={!imageProcessingEnabled}
                              >
                                <InputSelect.Trigger placeholder="Select a model" />
                                <InputSelect.Content />
                              </InputSelect>
                            </InputHorizontal>
                          </Disabled>

                          <Disabled disabled={!imageProcessingEnabled}>
                            <InputHorizontal
                              title="Max Image Size for Analysis"
                              suffix="(MB)"
                              description="Images above this size will be skipped to limit resource usage."
                              disabled={!imageProcessingEnabled}
                              withLabel
                            >
                              <InputSelect
                                value={String(
                                  settings.settings
                                    .image_analysis_max_size_mb ?? 20
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
                    </CloudDisabled>
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
