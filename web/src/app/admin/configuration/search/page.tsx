"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components-2/Text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import useSWR from "swr";
import { ModelPreview } from "@/components/embedding/ModelSelector";
import {
  HostedEmbeddingModel,
  CloudEmbeddingModel,
} from "@/components/embedding/interfaces";

import { ErrorCallout } from "@/components/ErrorCallout";

export interface EmbeddingDetails {
  api_key: string;
  custom_config: any;
  default_model_id?: number;
  name: string;
}

import { EmbeddingIcon } from "@/components/icons/icons";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";

import Link from "next/link";
import { SavedSearchSettings } from "../../embeddings/interfaces";
import UpgradingPage from "./UpgradingPage";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import CardSection from "@/components/admin/CardSection";

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
    <div className="py-padding-content">
      {searchSettingsPopup}

      {futureEmbeddingModel ? (
        <UpgradingPage futureEmbeddingModel={futureEmbeddingModel} />
      ) : (
        <div className="flex flex-col gap-padding-content">
          {settings?.settings.needs_reindexing && (
            <Text>
              Your search settings are currently out of date! We recommend
              updating your search settings and re-indexing.
            </Text>
          )}

          <div className="flex flex-col gap-padding-button">
            <Text headingH2>Embedding Model</Text>
            {currentEmeddingModel ? (
              <ModelPreview model={currentEmeddingModel} />
            ) : (
              <Text>Choose your Embedding Model</Text>
            )}
          </div>

          <div className="flex flex-col gap-padding-button">
            <Text headingH2>Post-processing</Text>
            <CardSection className="!w-96">
              {searchSettings && (
                <>
                  <div className="px-1 w-full rounded-lg">
                    <div className="space-y-4">
                      <div>
                        <Text>Reranking Model</Text>
                        <Text text04>
                          {searchSettings.rerank_model_name || "Not set"}
                        </Text>
                      </div>

                      <div>
                        <Text>Results to Rerank</Text>
                        <Text text04>{searchSettings.num_rerank}</Text>
                      </div>

                      <div>
                        <Text>Multilingual Expansion</Text>
                        <Text text04>
                          {searchSettings.multilingual_expansion.length > 0
                            ? searchSettings.multilingual_expansion.join(", ")
                            : "None"}
                        </Text>
                      </div>

                      <div>
                        <Text>Multipass Indexing</Text>
                        <Text text04>
                          {searchSettings.multipass_indexing
                            ? "Enabled"
                            : "Disabled"}
                        </Text>
                      </div>

                      <div>
                        <Text>Contextual RAG</Text>
                        <Text text04>
                          {searchSettings.enable_contextual_rag
                            ? "Enabled"
                            : "Disabled"}
                        </Text>
                      </div>

                      <div>
                        <Text>Disable Reranking for Streaming</Text>
                        <Text text04>
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
          </div>

          <Link href="/admin/embeddings">
            <Button variant="navigate" className="mt-spacing-paragraph">
              Update Search Settings
            </Button>
          </Link>
        </div>
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
