"use client";

import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, Card as CardLayout } from "@opal/layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Button, Card } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  HostedEmbeddingModel,
  CloudEmbeddingModel,
} from "@/components/embedding/interfaces";
import { SavedSearchSettings } from "@/app/admin/embeddings/interfaces";
import { getEmbeddingProvider } from "@/lib/embedding";
import UpgradingPage from "@/app/admin/configuration/search/UpgradingPage";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

export default function IndexSettingsPage() {
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

          <Card border="solid" rounding="lg" padding="fit">
            {/* Fields TBD */}
          </Card>
        </GeneralLayouts.Section>

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

          <Card border="solid" rounding="lg" padding="fit">
            {/* Fields TBD */}
          </Card>
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
