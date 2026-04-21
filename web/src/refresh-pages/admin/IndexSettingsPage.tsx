"use client";

import { useCallback, useMemo, useState } from "react";
import { markdown } from "@opal/utils";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  Content,
  Card as CardLayout,
  IllustrationContent,
} from "@opal/layouts";
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
  SvgCloud,
  SvgFold,
  SvgPlusCircle,
  SvgServer,
  SvgSettings,
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
  EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import type { EmbeddingModelState } from "@/lib/indexing/interfaces";
import {
  CLOUD_EMBEDDING_PROVIDERS,
  SELF_HOSTED_MODELS,
  findCloudProvider,
  getCurrentModelCopy,
  getEmbeddingProvider,
  getFormattedProviderName,
  MAX_IMAGE_SIZE_OPTIONS,
} from "@/lib/indexing";
import type { SelfHostedEmbeddingModel } from "@/lib/indexing/interfaces";
import Tabs from "@/refresh-components/Tabs";
import { saveAdminSettings, setNewSearchSettings } from "@/lib/indexing/svc";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import EditEmbeddingModelModal from "@/sections/modals/indexing/EditEmbeddingModelModal";
import ProviderCreationModal from "@/sections/modals/indexing/ProviderCreationModal";
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
  useSecondarySearchSettings,
} from "@/hooks/useSearchSettings";
import Spacer from "@/refresh-components/Spacer";
import useFilter from "@/hooks/useFilter";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

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

interface ProviderGroupProps {
  provider: CloudEmbeddingProvider;
  models: CloudEmbeddingModel[];
  currentModelName?: string;
  selectedModelName?: string;
  isConfigured?: boolean;
}

function ProviderGroup({
  provider,
  models,
  currentModelName,
  selectedModelName,
  isConfigured,
}: ProviderGroupProps) {
  const disconnectModal = useCreateModal();
  const providerCreationModal = useCreateModal();
  const providerName = getFormattedProviderName(provider.provider_type);
  const [pendingModel, setPendingModel] = useState<CloudEmbeddingModel | null>(
    null
  );

  const handleDisconnect = useCallback(async () => {
    const response = await fetch(
      `${EMBEDDING_PROVIDERS_ADMIN_URL}/${provider.provider_type}`,
      { method: "DELETE" }
    );

    if (!response.ok) {
      toast.error(`Failed to disconnect ${providerName}`);
      return;
    }

    toast.success(`Disconnected ${providerName}`);
    await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
    disconnectModal.toggle(false);
  }, [provider.provider_type, providerName, disconnectModal]);

  const selectModel = useCallback(async (model: CloudEmbeddingModel) => {
    const response = await setNewSearchSettings(model);

    if (!response.ok) {
      toast.error(`Failed to select ${model.model_name}`);
      return;
    }

    toast.success(`Selected ${model.model_name}`);
    await mutate("/api/search-settings/get-secondary-search-settings");
  }, []);

  const getModelState = useCallback(
    (model: CloudEmbeddingModel): EmbeddingModelState => {
      if (!isConfigured) return "unconnected";
      if (model.model_name === selectedModelName) return "selected";
      if (model.model_name === currentModelName) return "current";
      return "connected";
    },
    [isConfigured, selectedModelName, currentModelName]
  );

  const handleModelSelect = useCallback(
    (model: CloudEmbeddingModel) => {
      const state = getModelState(model);
      if (state === "current" || state === "selected") return;

      if (state === "unconnected") {
        setPendingModel(model);
        providerCreationModal.toggle(true);
        return;
      }

      void selectModel(model);
    },
    [getModelState, selectModel, providerCreationModal]
  );

  return (
    <GeneralLayouts.Section key={provider.provider_type} gap={0.25}>
      <disconnectModal.Provider>
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={markdown(`Disconnect *${providerName}*`)}
          submit={
            <Button variant="danger" onClick={handleDisconnect}>
              Disconnect
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03" as="p">
            {markdown(
              `This will disconnect all embedding models from provider **${providerName}**.`
            )}
          </Text>
        </ConfirmationModalLayout>
      </disconnectModal.Provider>

      <providerCreationModal.Provider>
        <ProviderCreationModal
          selectedProvider={provider}
          isProxy={provider.provider_type === EmbeddingProvider.LITELLM}
          isAzure={provider.provider_type === EmbeddingProvider.AZURE}
          updateCurrentModel={() => {}}
          onConfirm={async () => {
            await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
            providerCreationModal.toggle(false);
            if (pendingModel) {
              await selectModel(pendingModel);
              setPendingModel(null);
            }
          }}
          onCancel={() => {
            providerCreationModal.toggle(false);
            setPendingModel(null);
          }}
        />
      </providerCreationModal.Provider>

      <div className="px-1 pt-1 w-full h-[var(--line-height-lg)]">
        <GeneralLayouts.Section flexDirection="row" gap={0}>
          <Spacer horizontal rem={0.675} />
          <div className="flex flex-row justify-between items-center w-full py-1">
            <Content
              icon={provider.icon}
              title={markdown(
                `[${getFormattedProviderName(provider.provider_type)}](${
                  provider.docsLink
                })`
              )}
              sizePreset="secondary"
              variant="body"
            />
            {isConfigured && (
              <GeneralLayouts.Section
                flexDirection="row"
                gap={0.25}
                width="fit"
              >
                <Button
                  icon={SvgUnplug}
                  prominence="tertiary"
                  size="sm"
                  onClick={() => disconnectModal.toggle(true)}
                />
                {/* TODO(@raunakab): wire up */}
                <Button icon={SvgSettings} prominence="tertiary" size="sm" />
              </GeneralLayouts.Section>
            )}
          </div>
        </GeneralLayouts.Section>
      </div>
      {models.map((model) => (
        <EmbeddingModelCard
          key={model.model_name}
          model={model}
          providerIcon={provider.icon}
          modelState={getModelState(model)}
          onSelect={() => handleModelSelect(model)}
        />
      ))}
    </GeneralLayouts.Section>
  );
}

const SELECT_CARD_STATE: Record<
  EmbeddingModelState,
  "empty" | "filled" | "selected"
> = {
  unconnected: "filled",
  connected: "filled",
  current: "filled",
  selected: "selected",
};

interface EmbeddingModelCardProps {
  model: CloudEmbeddingModel;
  providerIcon: IconFunctionComponent;
  modelState: EmbeddingModelState;
  onSelect?: () => void;
}

function EmbeddingModelCard({
  model,
  providerIcon,
  modelState,
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
          >
            Connect
          </Button>
        );
      case "connected":
        return (
          <Button prominence="tertiary" onClick={onSelect}>
            Select Model
          </Button>
        );
      case "current":
        return (
          <Button variant="action" prominence="tertiary" icon={SvgCheckSquare}>
            Current Model
          </Button>
        );
      case "selected":
        return (
          <Button variant="action" prominence="tertiary" icon={SvgCheckSquare}>
            Selected
          </Button>
        );
    }
  })();

  return (
    <SelectCard
      state={SELECT_CARD_STATE[modelState]}
      rounding="md"
      padding="xs"
      onClick={
        modelState === "unconnected" || modelState === "connected"
          ? onSelect
          : undefined
      }
    >
      <CardLayout.Header
        headerChildren={
          <div className="flex flex-col">
            <Content
              icon={providerIcon}
              title={model.model_name}
              description={model.description}
              sizePreset="main-ui"
              variant="section"
            />
            <div className="flex flex-row px-6 pt-2 gap-4">
              <EmbeddingProviderInfo providerType={model.provider_type} />
            </div>
          </div>
        }
        topRightChildren={topRightButton}
      />
    </SelectCard>
  );
}

interface SelfHostedModelCardProps {
  model: SelfHostedEmbeddingModel;
  isSelected?: boolean;
}

function SelfHostedModelCard({ model, isSelected }: SelfHostedModelCardProps) {
  return (
    <SelectCard
      state={isSelected ? "selected" : "filled"}
      rounding="md"
      padding="xs"
    >
      <CardLayout.Header
        headerChildren={
          <div className="flex flex-col">
            <Content
              icon={SvgServer}
              title={model.model_name}
              description={model.description}
              sizePreset="main-ui"
              variant="section"
            />
            <div className="flex flex-row px-6 pt-2 gap-4">
              <EmbeddingProviderInfo providerType={null} />
              {model.link && (
                <LinkButton href={model.link} target="_blank">
                  Docs
                </LinkButton>
              )}
            </div>
          </div>
        }
      />
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
      <div className="px-1 pt-1 w-full h-[var(--line-height-lg)]">
        <GeneralLayouts.Section flexDirection="row" gap={0}>
          <Spacer horizontal rem={0.675} />
          <div className="flex flex-row justify-between items-center w-full py-1">
            <Content
              icon={provider.icon}
              title={markdown(`[${providerName}](${provider.docsLink})`)}
              sizePreset="secondary"
              variant="body"
            />
          </div>
        </GeneralLayouts.Section>
      </div>

      <providerCreationModal.Provider>
        <ProviderCreationModal
          selectedProvider={provider}
          isProxy={provider.provider_type === EmbeddingProvider.LITELLM}
          isAzure={provider.provider_type === EmbeddingProvider.AZURE}
          updateCurrentModel={() => {}}
          onConfirm={async () => {
            await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
            providerCreationModal.toggle(false);
          }}
          onCancel={() => providerCreationModal.toggle(false)}
        />
      </providerCreationModal.Provider>

      <SelectCard state="filled" rounding="md" padding="xs">
        <ContentAction
          icon={provider.icon}
          title={`Add configs for your ${providerName} embedding providers.`}
          sizePreset="main-ui"
          variant="section"
          padding="sm"
          rightChildren={
            <Button
              prominence="tertiary"
              rightIcon={SvgPlusCircle}
              onClick={() => providerCreationModal.toggle(true)}
            >
              Add Configuration
            </Button>
          }
        />
      </SelectCard>
    </GeneralLayouts.Section>
  );
}

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const editEmbeddingModelModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState("cloud");

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

  const filteredSelfHostedModels = useMemo(() => {
    const trimmed = modelSearchQuery.trim().toLowerCase();
    if (!trimmed) return SELF_HOSTED_MODELS;
    return SELF_HOSTED_MODELS.filter(
      (m) =>
        m.model_name.toLowerCase().includes(trimmed) ||
        m.description.toLowerCase().includes(trimmed)
    );
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
  const { data: secondarySettings } = useSecondarySearchSettings();

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
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          separator
        />
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
        separator
      />

      <SettingsLayouts.Body>
        <MessageCard
          title="Changes require a full re-index."
          description={markdown(
            "Modifying embedding settings requires a full re-index of all documents to take effect, which may take **hours or days** depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
          )}
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
                <editEmbeddingModelModal.Provider>
                  <EditEmbeddingModelModal provider={currentCloudProvider} />
                </editEmbeddingModelModal.Provider>
              )}

              <Tabs value={activeModelTab} onValueChange={setActiveModelTab}>
                <Card
                  expandable
                  expanded={viewAllModelsOpen}
                  border="solid"
                  rounding="lg"
                  padding={viewAllModelsOpen ? "fit" : "sm"}
                  expandedContent={
                    <>
                      <Tabs.Content value="cloud" className="pt-0">
                        {filteredProviders.length > 0 ||
                        configOnlyProviders.length > 0 ? (
                          <GeneralLayouts.Section gap={0.5} padding={0.5}>
                            {filteredProviders.map(({ provider, models }) => (
                              <ProviderGroup
                                key={provider.provider_type}
                                provider={provider}
                                models={models}
                                currentModelName={
                                  currentEmbeddingModel?.model_name
                                }
                                selectedModelName={
                                  secondarySettings?.model_name
                                }
                                isConfigured={configuredProviders?.has(
                                  provider.provider_type
                                )}
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
                            title="No cloud models found"
                            description="Try a different search term."
                          />
                        )}
                      </Tabs.Content>

                      <Tabs.Content value="self" className="pt-0">
                        {filteredSelfHostedModels.length > 0 ? (
                          <GeneralLayouts.Section gap={0.25} padding={0.5}>
                            {filteredSelfHostedModels.map((model) => (
                              <SelfHostedModelCard
                                key={model.model_name}
                                model={model}
                                isSelected={
                                  model.model_name ===
                                  currentEmbeddingModel?.model_name
                                }
                              />
                            ))}
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
                  <CardLayout.Header
                    headerChildren={
                      viewAllModelsOpen ? (
                        <div className="pt-1 px-1">
                          <div className="pt-2 px-2 flex flex-row items-center justify-between">
                            <InputTypeIn
                              placeholder="Search models..."
                              variant="internal"
                              leftSearchIcon
                              value={modelSearchQuery}
                              onChange={(e) =>
                                setModelSearchQuery(e.target.value)
                              }
                            />
                            <Button
                              prominence="internal"
                              onClick={() => setViewAllModelsOpen(false)}
                              rightIcon={SvgFold}
                            >
                              Fold Models
                            </Button>
                          </div>

                          <div className="px-2">
                            <Tabs.List variant="underline">
                              <Tabs.Trigger value="cloud">
                                Cloud Hosted
                              </Tabs.Trigger>
                              <Tabs.Trigger value="self">
                                Self Hosted
                              </Tabs.Trigger>
                            </Tabs.List>
                          </div>
                        </div>
                      ) : (
                        <GeneralLayouts.Section alignItems="start" gap={0}>
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
                      )
                    }
                    headerPadding={viewAllModelsOpen ? "fit" : undefined}
                    topRightChildren={
                      viewAllModelsOpen ? undefined : (
                        <div className="flex flex-col items-end justify-between p-2 gap-1">
                          <Button
                            prominence="secondary"
                            onClick={() => setViewAllModelsOpen(true)}
                          >
                            View All Models
                          </Button>
                          {currentCloudProvider && (
                            <div className="p-1">
                              <Button
                                icon={SvgSettings}
                                prominence="tertiary"
                                size="md"
                                onClick={() =>
                                  editEmbeddingModelModal.toggle(true)
                                }
                              />
                            </div>
                          )}
                        </div>
                      )
                    }
                  />
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
          <Card border="solid" rounding="lg">
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
