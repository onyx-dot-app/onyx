"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, Card as CardLayout } from "@opal/layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import { Button, Card, Divider } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import Switch from "@/refresh-components/inputs/Switch";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  HostedEmbeddingModel,
  CloudEmbeddingModel,
} from "@/components/embedding/interfaces";
import {
  SavedSearchSettings,
  LLMContextualCost,
} from "@/app/admin/embeddings/interfaces";
import { LLM_CONTEXTUAL_COST_ADMIN_URL } from "@/lib/llmConfig/constants";
import { getEmbeddingProvider } from "@/lib/embedding";
import UpgradingPage from "@/app/admin/configuration/search/UpgradingPage";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import Message from "@/refresh-components/messages/Message";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MAX_IMAGE_SIZE_OPTIONS = ["5", "10", "20", "50", "100"];

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const s = settings.settings;

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const currentSettings = s;
      if (!currentSettings) return;

      const newSettings = { ...currentSettings, ...updates };

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
    [s, router]
  );

  const imageProcessingEnabled =
    s.image_extraction_and_analysis_enabled ?? false;
  const {
    data: currentEmbeddingModel,
    isLoading: isLoadingCurrentModel,
    error: currentEmbeddingModelError,
  } = useSWR<CloudEmbeddingModel | HostedEmbeddingModel | null>(
    SWR_KEYS.currentSearchSettings,
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useSWR<SavedSearchSettings | null>(
      SWR_KEYS.currentSearchSettings,
      errorHandlingFetcher,
      { refreshInterval: 5000 }
    );

  const {
    data: futureEmbeddingModel,
    isLoading: isLoadingFutureModel,
    error: futureEmbeddingModelError,
  } = useSWR<CloudEmbeddingModel | HostedEmbeddingModel | null>(
    SWR_KEYS.secondarySearchSettings,
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: contextualCosts } = useSWR<LLMContextualCost[]>(
    LLM_CONTEXTUAL_COST_ADMIN_URL,
    errorHandlingFetcher
  );

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

  if (
    isLoadingCurrentModel ||
    isLoadingFutureModel ||
    isLoadingSearchSettings
  ) {
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

  // While an embedding model upgrade is in progress, show the legacy
  // UpgradingPage (will be reskinned in a follow-up PR).
  if (futureEmbeddingModel) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          separator
        />
        <SettingsLayouts.Body>
          <UpgradingPage futureEmbeddingModel={futureEmbeddingModel} />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />

      <SettingsLayouts.Body>
        <Message
          static
          info
          close={false}
          text="Changes to indexing settings will apply to newly indexed documents. Existing documents will retain their current settings until re-indexed."
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
            <Card border="solid" rounding="lg" padding="sm">
              <CardLayout.Header
                icon={
                  getEmbeddingProvider(currentEmbeddingModel.provider_type).icon
                }
                title={currentEmbeddingModel.model_name}
                description={currentEmbeddingModel.description}
                sizePreset="main-ui"
                variant="section"
                rightChildren={
                  // TODO(@raunakab): Wire up later.
                  <div className="flex flex-col items-end justify-between p-2 gap-1">
                    <Button prominence="secondary">View All Models</Button>
                    <div className="p-1">
                      <Button icon={SvgSettings} prominence="tertiary" />
                    </div>
                  </div>
                }
              />
            </Card>
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
                    value={String(s.image_analysis_max_size_mb ?? 20)}
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
