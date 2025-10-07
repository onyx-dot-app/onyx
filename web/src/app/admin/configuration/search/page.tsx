"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import Button from "@/refresh-components/buttons/Button";
import useSWR from "swr";
import { ModelPreview } from "@/components/embedding/ModelSelector";
import {
  HostedEmbeddingModel,
  CloudEmbeddingModel,
} from "@/components/embedding/interfaces";
import { SavedSearchSettings } from "@/app/admin/embeddings/interfaces";
import UpgradingPage from "./UpgradingPage";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import CardSection from "@/components/admin/CardSection";
import { ErrorCallout } from "@/components/ErrorCallout";

export interface EmbeddingDetails {
  api_key: string;
  custom_config: any;
  default_model_id?: number;
  name: string;
}

import { EmbeddingIcon } from "@/components/icons/icons";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";

function Main() {
  const settings = useContext(SettingsContext);
  const { popup: searchSettingsPopup } = usePopupFromQuery({
    "search-settings": {
      message: `Changed search settings successfully`,
      type: "success",
    },
  });
  const {
    data: currentEmeddingModel,
    isLoading: isLoadingCurrentModel,
    error: currentEmeddingModelError,
  } = useSWR<CloudEmbeddingModel | HostedEmbeddingModel | null>(
    "/api/search-settings/get-current-search-settings",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useSWR<SavedSearchSettings | null>(
      "/api/search-settings/get-current-search-settings",
      errorHandlingFetcher,
      { refreshInterval: 5000 } // 5 seconds
    );

  const {
    data: futureEmbeddingModel,
    isLoading: isLoadingFutureModel,
    error: futureEmeddingModelError,
  } = useSWR<CloudEmbeddingModel | HostedEmbeddingModel | null>(
    "/api/search-settings/get-secondary-search-settings",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  if (
    isLoadingCurrentModel ||
    isLoadingFutureModel ||
    isLoadingSearchSettings
  ) {
    return <ThreeDotsLoader />;
  }

  if (
    currentEmeddingModelError ||
    !currentEmeddingModel ||
    futureEmeddingModelError
  ) {
    return <ErrorCallout errorTitle="Failed to fetch embedding model status" />;
  }

  return (
    <div className="h-screen">
      {searchSettingsPopup}
      {!futureEmbeddingModel ? (
        <>
          {settings?.settings.needs_reindexing && (
            <p className="max-w-3xl">
              Your search settings are currently out of date! We recommend
              updating your search settings and re-indexing.
            </p>
          )}
          <Title className="mb-6 mt-8 !text-2xl">Embedding Model</Title>

          {currentEmeddingModel ? (
            <ModelPreview model={currentEmeddingModel} display showDetails />
          ) : (
            <Title className="mt-8 mb-4">Choose your Embedding Model</Title>
          )}

          <Title className="mb-2 mt-8 !text-2xl">Post-processing</Title>

          <CardSection className="!mr-auto mt-8 !w-96 shadow-lg bg-background-tint-00 rounded-16">
            {searchSettings && (
              <>
                <div className="px-1 w-full rounded-lg">
                  <div className="space-y-4">
                    <div>
                      <Text className="font-semibold">Reranking Model</Text>
                      <Text className="text-text-700">
                        {searchSettings.rerank_model_name || "Not set"}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">Results to Rerank</Text>
                      <Text className="text-text-700">
                        {searchSettings.num_rerank}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        Multilingual Expansion
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.multilingual_expansion.length > 0
                          ? searchSettings.multilingual_expansion.join(", ")
                          : "None"}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">Multipass Indexing</Text>
                      <Text className="text-text-700">
                        {searchSettings.multipass_indexing
                          ? "Enabled"
                          : "Disabled"}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">Contextual RAG</Text>
                      <Text className="text-text-700">
                        {searchSettings.enable_contextual_rag
                          ? "Enabled"
                          : "Disabled"}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        Disable Reranking for Streaming
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.disable_rerank_for_streaming
                          ? "Yes"
                          : "No"}
                      </Text>
                    </div>
                  </div>
                </div>
              </>
            )}
          </CardSection>

          <div className="mt-4">
            <Button action href="/admin/embeddings">
              Update Search Settings
            </Button>
          </div>
        </>
      ) : (
        <UpgradingPage futureEmbeddingModel={futureEmbeddingModel} />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Search Settings"
        icon={<EmbeddingIcon size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
