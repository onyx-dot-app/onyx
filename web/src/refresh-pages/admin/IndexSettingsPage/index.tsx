"use client";

import { useCallback, useMemo, useRef, useState } from "react";
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
  SvgFold,
  SvgNoImage,
  SvgPlusCircle,
  SvgRevert,
  SvgServer,
  SvgSettings,
  SvgSlowTime,
  SvgUnplug,
} from "@opal/icons";
import Switch from "@/refresh-components/inputs/Switch";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import type { IconFunctionComponent } from "@opal/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  SavedSearchSettings,
  CloudEmbeddingModel,
  CloudEmbeddingProvider,
  EmbeddingProviderName,
  SelfHostedEmbeddingModel,
  SwitchoverType,
} from "@/lib/indexing/interfaces";
import type {
  ConfiguredEmbeddingProvider,
  EmbeddingModelState,
} from "@/lib/indexing/interfaces";
import {
  CLOUD_EMBEDDING_PROVIDERS,
  SELF_HOSTED_MODELS,
  SELF_HOSTED_PROVIDERS,
  findCloudProvider,
  getCurrentModelCopy,
  getEmbeddingProvider,
  getFormattedProviderName,
  MAX_IMAGE_SIZE_OPTIONS,
} from "@/lib/indexing";
import Tabs from "@/refresh-components/Tabs";
import {
  saveAdminSettings,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
} from "@/lib/indexing/svc";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ContentAction } from "@opal/layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { EMBEDDING_PROVIDERS_ADMIN_URL } from "@/lib/indexing";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useLLMContextualCosts,
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

interface EmbeddingProviderInfoProps {
  providerType: string | null;
}

function EmbeddingProviderInfo({ providerType }: EmbeddingProviderInfoProps) {
  if (!providerType) {
    return (
      <Content
        icon={SvgServer}
        title="Self-hosted"
        sizePreset="secondary"
        variant="body"
        prominence="muted"
        width="fit"
        nonInteractive
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
        prominence="muted"
        width="fit"
        nonInteractive
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

interface ProviderGroupHeaderProps {
  icon: IconFunctionComponent;
  name: string;
  docsLink?: string;
  suffix?: string;
  rightChildren?: React.ReactNode;
}

function ProviderGroupHeader({
  icon,
  name,
  docsLink,
  suffix,
  rightChildren,
}: ProviderGroupHeaderProps) {
  return (
    <div className="px-1 pt-1 w-full h-[var(--opal-line-height-lg)]">
      <GeneralLayouts.Section flexDirection="row" gap={0}>
        <Spacer horizontal rem={0.675} />
        <div className="flex flex-row justify-between items-center w-full py-1">
          <Content
            icon={icon}
            title={docsLink ? markdown(`[${name}](${docsLink})`) : name}
            suffix={suffix}
            sizePreset="secondary"
          />
          {rightChildren}
        </div>
      </GeneralLayouts.Section>
    </div>
  );
}

interface ProviderGroupProps {
  icon: IconFunctionComponent;
  name: string;
  docsLink?: string;
  deprecated?: boolean;
  models: (CloudEmbeddingModel | SelfHostedEmbeddingModel)[];
  currentModelName?: string;
  selectedModelName?: string;
  cloudProvider?: CloudEmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
  onSelectModel: (modelName: string) => void;
  onDeselectModel: () => void;
}

function ProviderGroup({
  icon,
  name,
  docsLink,
  deprecated,
  models,
  currentModelName,
  selectedModelName,
  cloudProvider,
  existingCredentials,
  onSelectModel,
  onDeselectModel,
}: ProviderGroupProps) {
  const isCloud = !!cloudProvider;
  const isConfigured = isCloud ? !!existingCredentials : true;
  const disconnectModal = useCreateModal();
  const connectModal = useCreateModal();
  const editCredentialsModal = useCreateModal();
  const [pendingModel, setPendingModel] = useState<
    CloudEmbeddingModel | SelfHostedEmbeddingModel | null
  >(null);

  const handleDisconnect = useCallback(async () => {
    if (!cloudProvider) return;
    try {
      await disconnectEmbeddingProvider(cloudProvider.provider_type);
      toast.success(`Disconnected ${name}`);
      await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
      disconnectModal.toggle(false);
    } catch {
      toast.error(`Failed to disconnect ${name}`);
    }
  }, [cloudProvider, name, disconnectModal]);

  const getModelState = useCallback(
    (
      model: CloudEmbeddingModel | SelfHostedEmbeddingModel
    ): EmbeddingModelState => {
      if (isCloud && !isConfigured) return "unconnected";
      if (model.model_name === selectedModelName) return "selected";
      if (model.model_name === currentModelName) return "current";
      return "connected";
    },
    [isCloud, isConfigured, selectedModelName, currentModelName]
  );

  const handleModelSelect = useCallback(
    (model: CloudEmbeddingModel | SelfHostedEmbeddingModel) => {
      if (deprecated) return;
      const state = getModelState(model);

      if (state === "selected" || state === "current") {
        onDeselectModel();
        return;
      }

      if (state === "unconnected" && cloudProvider) {
        setPendingModel(model);
        connectModal.toggle(true);
        return;
      }

      onSelectModel(model.model_name);
    },
    [
      getModelState,
      onSelectModel,
      onDeselectModel,
      connectModal,
      deprecated,
      cloudProvider,
    ]
  );

  return (
    <GeneralLayouts.Section gap={0.25}>
      {cloudProvider && (
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
              provider={cloudProvider}
              onSubmit={async () => {
                await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
                connectModal.toggle(false);
                if (pendingModel) {
                  onSelectModel(pendingModel.model_name);
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
              provider={cloudProvider}
              existingCredentials={existingCredentials}
              onSubmit={async () => {
                await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
                editCredentialsModal.toggle(false);
              }}
              onCancel={() => editCredentialsModal.toggle(false)}
            />
          </editCredentialsModal.Provider>
        </>
      )}

      <ProviderGroupHeader
        icon={icon}
        name={name}
        docsLink={docsLink}
        suffix={deprecated ? "(deprecated)" : undefined}
        rightChildren={
          isCloud && isConfigured ? (
            <GeneralLayouts.Section flexDirection="row" gap={0.25} width="fit">
              <Button
                icon={SvgUnplug}
                prominence="tertiary"
                size="sm"
                disabled={models.some((m) => m.model_name === currentModelName)}
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
          ) : undefined
        }
      />
      {models.map((model) => (
        <EmbeddingModelCard
          key={model.model_name}
          icon={icon}
          modelName={model.model_name}
          description={model.description}
          providerType={model.provider_type}
          docsLink={"link" in model ? model.link : undefined}
          modelState={getModelState(model)}
          deprecated={deprecated}
          onSelect={() => handleModelSelect(model)}
        />
      ))}
    </GeneralLayouts.Section>
  );
}

interface EmbeddingModelCardProps {
  icon: IconFunctionComponent;
  modelName: string;
  description: string;
  providerType: string | null;
  docsLink?: string;
  modelState: EmbeddingModelState;
  deprecated?: boolean;
  onSelect?: () => void;
}

function EmbeddingModelCard({
  icon,
  modelName,
  description,
  providerType,
  docsLink,
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
            icon={icon}
            title={modelName}
            description={description}
            sizePreset="main-ui"
            variant="section"
          />
          <div className="flex flex-row px-6 pt-2 gap-4">
            <EmbeddingProviderInfo providerType={providerType} />
            {docsLink && (
              <LinkButton href={docsLink} target="_blank">
                Docs
              </LinkButton>
            )}
          </div>
        </GeneralLayouts.Section>
        {topRightButton && <div className="shrink-0">{topRightButton}</div>}
      </GeneralLayouts.Section>
    </SelectCard>
  );
}

interface ConfigOnlyProviderCardProps {
  provider: CloudEmbeddingProvider;
}

function ConfigOnlyProviderCard({ provider }: ConfigOnlyProviderCardProps) {
  const providerCreationModal = useCreateModal();
  const providerName = getFormattedProviderName(provider.provider_type);

  return (
    <GeneralLayouts.Section key={provider.provider_type} gap={0.25}>
      <ProviderGroupHeader
        icon={provider.icon}
        name={getFormattedProviderName(provider.provider_type)}
        docsLink={provider.docsLink}
      />

      <providerCreationModal.Provider>
        <ProviderCredentialsModal
          provider={provider}
          onSubmit={async () => {
            await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
            providerCreationModal.toggle(false);
          }}
          onCancel={() => providerCreationModal.toggle(false)}
        />
      </providerCreationModal.Provider>

      <SelectCard
        state="filled"
        rounding="md"
        padding="sm"
        onClick={() => providerCreationModal.toggle(true)}
      >
        <ContentAction
          title={`Add configs for your ${providerName} embedding providers.`}
          sizePreset="secondary"
          variant="body"
          prominence="muted"
          nonInteractive
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
    </GeneralLayouts.Section>
  );
}

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const collapsedEditModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState(MODEL_TAB_CLOUD);
  const [selectedModelName, setSelectedModelName] = useState<string | null>(
    null
  );
  const [switchoverType, setSwitchoverType] = useState<
    SwitchoverType | typeof SWITCHOVER_NONE
  >(SWITCHOVER_NONE);

  const allCloudProviders = useMemo(
    () =>
      Object.values(CLOUD_EMBEDDING_PROVIDERS).filter(
        (p) => p.embedding_models.length > 0
      ),
    []
  );

  const configOnlyProviders = useMemo(
    () =>
      Object.values(CLOUD_EMBEDDING_PROVIDERS).filter(
        (p) => p.embedding_models.length === 0
      ),
    []
  );

  const allCloudModels = useMemo(
    () =>
      allCloudProviders.flatMap((p) =>
        p.embedding_models.map((m) => ({ model: m, provider: p }))
      ),
    [allCloudProviders]
  );

  const {
    query: modelSearchQuery,
    setQuery: setModelSearchQuery,
    filtered: filteredCloudModels,
  } = useFilter(
    allCloudModels,
    (item) =>
      `${item.model.model_name} ${
        item.model.description
      } ${getFormattedProviderName(item.provider.provider_type)}`
  );

  const filteredProviders = useMemo(() => {
    const modelsByProvider = new Map<string, CloudEmbeddingModel[]>();
    for (const { model, provider } of filteredCloudModels) {
      const key = provider.provider_type;
      if (!modelsByProvider.has(key)) modelsByProvider.set(key, []);
      modelsByProvider.get(key)!.push(model);
    }
    return allCloudProviders
      .filter((p) => modelsByProvider.has(p.provider_type))
      .map((p) => ({
        provider: p,
        models: modelsByProvider.get(p.provider_type)!,
      }));
  }, [filteredCloudModels, allCloudProviders]);

  const filteredSelfHostedProviders = useMemo(() => {
    const trimmed = modelSearchQuery.trim().toLowerCase();
    return SELF_HOSTED_PROVIDERS.map((provider) => ({
      provider,
      models: trimmed
        ? provider.embedding_models.filter(
            (m) =>
              m.model_name.toLowerCase().includes(trimmed) ||
              m.description.toLowerCase().includes(trimmed) ||
              provider.provider_name.toLowerCase().includes(trimmed)
          )
        : provider.embedding_models,
    })).filter(({ models }) => models.length > 0);
  }, [modelSearchQuery]);

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

  const handleApply = useCallback(async () => {
    if (!selectedModelName) return;

    const model = getCurrentModelCopy(selectedModelName);
    if (!model) {
      toast.error("Could not find the selected model");
      return;
    }

    if (switchoverType === SWITCHOVER_NONE) {
      toast.success("Settings applied");
      setSelectedModelName(null);
      setSwitchoverType(SWITCHOVER_NONE);
      return;
    }

    const response = await setNewSearchSettings(
      model,
      switchoverType as SwitchoverType
    );

    if (!response.ok) {
      toast.error("Failed to apply settings");
      return;
    }

    toast.success("Re-indexing started");
    setSelectedModelName(null);
    setSwitchoverType(SWITCHOVER_NONE);
    await Promise.all([
      mutate(SWR_KEYS.currentSearchSettings),
      mutate("/api/search-settings/get-secondary-search-settings"),
    ]);
  }, [selectedModelName, switchoverType]);

  const statusVariant = selectedModelName
    ? switchoverType === SWITCHOVER_NONE
      ? "info"
      : "warning"
    : undefined;

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

  const saveSearchSettings = useCallback(
    async (updates: Partial<SavedSearchSettings>) => {
      if (!searchSettings) return;

      try {
        const response = await fetch(
          "/api/search-settings/update-inference-settings",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...searchSettings, ...updates }),
          }
        );

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }

        await mutate(SWR_KEYS.currentSearchSettings);
        toast.success("Search settings updated");
      } catch {
        toast.error("Failed to update search settings");
      }
    },
    [searchSettings]
  );

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
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Configure how documents are indexed, embedded, and prepared for search and retrieval."
        divider
      />

      <SettingsLayouts.Body>
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
              ? "Image processing settings will take effect only for documents indexed going forward. Existing documents will not be updated unless you run a full re-index.\nRe-indexing may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)\nYou can monitor the re-indexing progress on this page."
              : statusVariant === "warning"
                ? "Modifying embedding settings requires a full re-index of all documents to take effect, which may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)\nYou can monitor the re-indexing progress on this page."
                : "Modifying embedding settings requires a full re-index of all documents to take effect, which may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
          )}
          bottomChildren={
            selectedModelName ? (
              <div className="flex flex-row items-end gap-4 p-2">
                <div className="flex-1 min-w-0">
                  <InputSelect
                    value={switchoverType}
                    onValueChange={(v) =>
                      setSwitchoverType(
                        v as SwitchoverType | typeof SWITCHOVER_NONE
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
                      setSelectedModelName(null);
                      setSwitchoverType(SWITCHOVER_NONE);
                    }}
                  >
                    Revert
                  </Button>
                  <Button onClick={handleApply}>
                    {switchoverType === SWITCHOVER_NONE
                      ? "Apply without Re-index"
                      : "Apply & Re-index"}
                  </Button>
                </div>
              </div>
            ) : undefined
          }
        />

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

          {currentEmbeddingModel && (
            <>
              {currentCloudProvider && (
                <collapsedEditModal.Provider>
                  <ProviderCredentialsModal
                    provider={currentCloudProvider}
                    existingCredentials={configuredProviders?.get(
                      currentCloudProvider.provider_type
                    )}
                    onSubmit={async () => {
                      await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
                      collapsedEditModal.toggle(false);
                    }}
                    onCancel={() => collapsedEditModal.toggle(false)}
                  />
                </collapsedEditModal.Provider>
              )}

              <Tabs value={activeModelTab} onValueChange={setActiveModelTab}>
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
                      <Tabs.Content value={MODEL_TAB_CLOUD} className="pt-0">
                        {filteredProviders.length > 0 ||
                        configOnlyProviders.length > 0 ? (
                          <GeneralLayouts.Section gap={0.5} padding={0.5}>
                            {filteredProviders.map(({ provider, models }) => (
                              <ProviderGroup
                                key={provider.provider_type}
                                icon={provider.icon}
                                name={getFormattedProviderName(
                                  provider.provider_type
                                )}
                                docsLink={provider.docsLink}
                                deprecated={provider.deprecated}
                                models={models}
                                currentModelName={
                                  currentEmbeddingModel?.model_name
                                }
                                selectedModelName={
                                  selectedModelName ?? undefined
                                }
                                cloudProvider={provider}
                                existingCredentials={configuredProviders?.get(
                                  provider.provider_type
                                )}
                                onSelectModel={setSelectedModelName}
                                onDeselectModel={() =>
                                  setSelectedModelName(null)
                                }
                              />
                            ))}
                            {configOnlyProviders.map((provider) => (
                              <ConfigOnlyProviderCard
                                key={provider.provider_type}
                                provider={provider}
                              />
                            ))}
                          </GeneralLayouts.Section>
                        ) : (
                          <IllustrationContent
                            illustration={SvgNoResult}
                            title="No cloud-based models found"
                            description="Try a different search term."
                          />
                        )}
                      </Tabs.Content>

                      <Tabs.Content value={MODEL_TAB_SELF} className="pt-0">
                        {filteredSelfHostedProviders.length > 0 ? (
                          <GeneralLayouts.Section gap={0.5} padding={0.5}>
                            {filteredSelfHostedProviders.map(
                              ({ provider: shProvider, models }) => (
                                <ProviderGroup
                                  key={shProvider.provider_name}
                                  icon={shProvider.icon}
                                  name={shProvider.provider_name}
                                  docsLink={shProvider.docsLink}
                                  models={models}
                                  currentModelName={
                                    currentEmbeddingModel?.model_name
                                  }
                                  selectedModelName={
                                    selectedModelName ?? undefined
                                  }
                                  onSelectModel={setSelectedModelName}
                                  onDeselectModel={() =>
                                    setSelectedModelName(null)
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
                          value={modelSearchQuery}
                          onChange={(e) => setModelSearchQuery(e.target.value)}
                        />
                        <div className="flex flex-row">
                          {selectedModelName && (
                            <Button
                              icon={SvgRevert}
                              prominence="internal"
                              onClick={() => {
                                setSelectedModelName(null);
                                setSwitchoverType(SWITCHOVER_NONE);
                              }}
                            />
                          )}
                          <Button
                            prominence="internal"
                            onClick={() => setViewAllModelsOpen(false)}
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
                              currentEmbeddingModel.provider_type
                            ).icon
                          }
                          title={currentEmbeddingModel.model_name}
                          description={
                            getCurrentModelCopy(
                              currentEmbeddingModel.model_name
                            )?.description
                          }
                          sizePreset="main-ui"
                          variant="section"
                        />
                        <div className="flex flex-row items-center gap-2 pt-2 px-6">
                          <EmbeddingProviderInfo
                            providerType={currentEmbeddingModel.provider_type}
                          />
                        </div>
                      </GeneralLayouts.Section>

                      <div className="flex flex-col justify-start items-end shrink-0 gap-1 p-2">
                        <Button
                          prominence="secondary"
                          onClick={() => {
                            const isSelectedSelfHosted =
                              selectedModelName &&
                              SELF_HOSTED_MODELS.some(
                                (m) => m.model_name === selectedModelName
                              );
                            setActiveModelTab(
                              isSelectedSelfHosted
                                ? MODEL_TAB_SELF
                                : selectedModelName
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
                              onClick={() => collapsedEditModal.toggle(true)}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </Card>
              </Tabs>
            </>
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

          <Card border="solid" rounding="lg">
            <Disabled disabled>
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
                  checked={searchSettings?.multipass_indexing ?? false}
                  disabled
                />
              </InputHorizontal>
            </Disabled>
          </Card>

          {/* TODO(@raunakab): enable_contextual_rag is in PRESERVED_SEARCH_FIELDS
             (backend/shared_configs/configs.py), so the update-inference-settings
             endpoint silently ignores it. The backend returns 200 but never persists
             the change. Needs a backend fix to remove it from the preserved list. */}
          <Card border="solid" borderColor={statusVariant} rounding="lg">
            <GeneralLayouts.Section width="full">
              <InputHorizontal
                title="Contextual Retrieval"
                description="Add document-level context to every indexed chunk to improve hybrid search relevance. This can increase embedding cost significantly."
                withLabel
              >
                <Switch
                  checked={searchSettings?.enable_contextual_rag ?? false}
                  onCheckedChange={(checked) => {
                    void saveSearchSettings({ enable_contextual_rag: checked });
                  }}
                />
              </InputHorizontal>

              <Disabled disabled={!searchSettings?.enable_contextual_rag}>
                <InputHorizontal
                  title="Contextual Retrieval LLM"
                  description="This model will be used to generate context for chunks."
                  disabled={!searchSettings?.enable_contextual_rag}
                  withLabel
                >
                  <InputSelect
                    value={searchSettings?.contextual_rag_llm_name ?? ""}
                    onValueChange={(value) => {
                      const selectedModel = contextualCosts?.find(
                        (cost) => cost.model_name === value
                      );
                      void saveSearchSettings({
                        contextual_rag_llm_name: value,
                        contextual_rag_llm_provider:
                          selectedModel?.provider ?? null,
                      });
                    }}
                    disabled={!searchSettings?.enable_contextual_rag}
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
        </GeneralLayouts.Section>

        <Divider />

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

          <Card border="solid" borderColor={statusVariant} rounding="lg">
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
                      image_extraction_and_analysis_enabled: checked,
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
                      settings.settings.image_analysis_max_size_mb ?? 20
                    )}
                    onValueChange={(value) => {
                      void saveSettings({
                        image_analysis_max_size_mb: parseInt(value, 10),
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
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
