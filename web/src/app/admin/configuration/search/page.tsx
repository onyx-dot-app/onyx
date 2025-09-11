"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import useSWR from "swr";
import { ModelPreview } from "../../../../components/embedding/ModelSelector";
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
    <div className="h-screen">
      {searchSettingsPopup}
      {!futureEmbeddingModel ? (
        <>
          {settings?.settings.needs_reindexing && (
            <p className="max-w-3xl">
              {i18n.t(k.YOUR_SEARCH_SETTINGS_ARE_CURRE)}
            </p>
          )}
          <Title className="mb-6 mt-8 !text-2xl">
            {i18n.t(k.EMBEDDING_MODEL)}
          </Title>

          {currentEmeddingModel ? (
            <ModelPreview model={currentEmeddingModel} display />
          ) : (
            <Title className="mt-8 mb-4">
              {i18n.t(k.CHOOSE_YOUR_EMBEDDING_MODEL)}
            </Title>
          )}

          <Title className="mb-2 mt-8 !text-2xl">
            {i18n.t(k.POST_PROCESSING)}
          </Title>

          <CardSection className="!mr-auto mt-8 !w-96">
            {searchSettings && (
              <>
                <div className="px-1 w-full rounded-lg">
                  <div className="space-y-4">
                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.RERANKING_MODEL)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.rerank_model_name || i18n.t(k.NOT_SET)}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.RESULTS_TO_RERANK)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.num_rerank}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.MULTILINGUAL_EXPANSION)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.multilingual_expansion.length > 0
                          ? searchSettings.multilingual_expansion.join(
                              i18n.t(k._3)
                            )
                          : i18n.t(k.NONE)}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.MULTIPASS_INDEXING)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.multipass_indexing
                          ? i18n.t(k.ENABLED)
                          : i18n.t(k.DISABLED)}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.CONTEXTUAL_RAG)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.enable_contextual_rag
                          ? i18n.t(k.ENABLED)
                          : i18n.t(k.DISABLED)}
                      </Text>
                    </div>

                    <div>
                      <Text className="font-semibold">
                        {i18n.t(k.DISABLE_RERANKING_FOR_STREAMIN)}
                      </Text>
                      <Text className="text-text-700">
                        {searchSettings.disable_rerank_for_streaming
                          ? i18n.t(k.YES)
                          : i18n.t(k.NO)}
                      </Text>
                    </div>
                  </div>
                </div>
              </>
            )}
          </CardSection>

          <Link href="/admin/embeddings">
            <Button variant="navigate" className="mt-8">
              {i18n.t(k.UPDATE_SEARCH_SETTINGS)}
            </Button>
          </Link>
        </>
      ) : (
        <UpgradingPage futureEmbeddingModel={futureEmbeddingModel} />
      )}
    </div>
  );
}

function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title={i18n.t(k.SEARCH_SETTINGS)}
        icon={<EmbeddingIcon size={32} className="my-auto" />}
      />

      <Main />
    </div>
  );
}

export default Page;
