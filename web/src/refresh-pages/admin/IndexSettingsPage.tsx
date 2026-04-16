"use client";

import { useCallback } from "react";
import { markdown } from "@opal/utils";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, Card as CardLayout } from "@opal/layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import {
  Button,
  Card,
  Divider,
  LinkButton,
  MessageCard,
} from "@opal/components";
import { SvgCloud, SvgServer, SvgSettings } from "@opal/icons";
import Switch from "@/refresh-components/inputs/Switch";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SavedSearchSettings } from "@/lib/indexing/interfaces";
import {
  findCloudProvider,
  getCurrentModelCopy,
  getEmbeddingProvider,
  MAX_IMAGE_SIZE_OPTIONS,
} from "@/lib/indexing";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import EditEmbeddingModelModal from "@/sections/modals/indexing/EditEmbeddingModelModal";

import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import {
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useLLMContextualCosts,
} from "@/hooks/useSearchSettings";

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

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const editEmbeddingModelModal = useCreateModal();

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      if (!settings.settings) return;

      const newSettings = { ...settings.settings, ...updates };

      try {
        const response = await fetch("/api/admin/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSettings),
        });

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }

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
            "Modifying embedding settings requires a full re-index of all documents to take effect, which may take *hours or days* depending on corpus size. [Learn More](https://docs.onyx.app/security/architecture/data_flows)"
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

              <Card border="solid" rounding="lg" padding="sm">
                <CardLayout.Header
                  headerChildren={
                    <GeneralLayouts.Section alignItems="start" gap={0}>
                      <Content
                        icon={
                          getEmbeddingProvider(
                            currentEmbeddingModel.provider_type
                          ).icon
                        }
                        title={currentEmbeddingModel.model_name}
                        description={
                          getCurrentModelCopy(currentEmbeddingModel.model_name)
                            ?.description
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
                  }
                  topRightChildren={
                    // TODO(@raunakab): Wire up "View All Models" later.
                    <div className="flex flex-col items-end justify-between p-2 gap-1">
                      <Button prominence="secondary">View All Models</Button>
                      {currentCloudProvider && (
                        <div className="p-1">
                          <Button
                            icon={SvgSettings}
                            prominence="tertiary"
                            size="md"
                            onClick={() => editEmbeddingModelModal.toggle(true)}
                          />
                        </div>
                      )}
                    </div>
                  }
                />
              </Card>
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
                  <InputSelect
                    value=""
                    onValueChange={() => {}}
                    disabled={!imageProcessingEnabled}
                  >
                    <InputSelect.Trigger placeholder="Select a model" />
                    <InputSelect.Content>
                      {/* TODO: Populate with available LLM models */}
                    </InputSelect.Content>
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
