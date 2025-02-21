"use client";
import { usePopup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { EmbeddingModelSelection } from "../EmbeddingModelSelectionForm";
import { useCallback, useEffect, useMemo, useState } from "react";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { ArrowLeft, ArrowRight, WarningCircle } from "@phosphor-icons/react";
import {
  CloudEmbeddingModel,
  EmbeddingProvider,
  HostedEmbeddingModel,
} from "@/components/embedding/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import AdvancedEmbeddingFormPage from "./AdvancedEmbeddingFormPage";
import {
  AdvancedSearchConfiguration,
  RerankingDetails,
  SavedSearchSettings,
} from "../interfaces";
import RerankingDetailsForm from "../RerankingFormPage";
import { useEmbeddingFormContext } from "@/components/context/EmbeddingContext";
import { Modal } from "@/components/Modal";

import { useRouter } from "next/navigation";
import CardSection from "@/components/admin/CardSection";
import { combineSearchSettings } from "./utils";

export default function EmbeddingForm() {
  const { formStep, nextFormStep, prevFormStep } = useEmbeddingFormContext();
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const [advancedEmbeddingDetails, setAdvancedEmbeddingDetails] =
    useState<AdvancedSearchConfiguration>({
      index_name: "",
      multipass_indexing: true,
      multilingual_expansion: [],
      disable_rerank_for_streaming: false,
      api_url: null,
      num_rerank: 0,
    });

  const [rerankingDetails, setRerankingDetails] = useState<RerankingDetails>({
    rerank_api_key: "",
    rerank_provider_type: null,
    rerank_model_name: "",
    rerank_api_url: null,
  });

  const updateAdvancedEmbeddingDetails = (
    key: keyof AdvancedSearchConfiguration,
    value: any
  ) => {
    setAdvancedEmbeddingDetails((values) => ({ ...values, [key]: value }));
  };

  async function updateSearchSettings(searchSettings: SavedSearchSettings) {
    const response = await fetch(
      "/api/search-settings/update-inference-settings",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...searchSettings,
        }),
      }
    );
    return response;
  }

  const updateSelectedProvider = (
    model: CloudEmbeddingModel | HostedEmbeddingModel
  ) => {
    setSelectedProvider(model);
  };
  const [displayPoorModelName, setDisplayPoorModelName] = useState(true);
  const [showPoorModel, setShowPoorModel] = useState(false);
  const [modelTab, setModelTab] = useState<"open" | "cloud" | null>(null);

  const {
    data: currentEmbeddingModel,
    isLoading: isLoadingCurrentModel,
    error: currentEmbeddingModelError,
  } = useSWR<CloudEmbeddingModel | HostedEmbeddingModel | null>(
    "/api/search-settings/get-current-search-settings",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const [selectedProvider, setSelectedProvider] = useState<
    CloudEmbeddingModel | HostedEmbeddingModel | null
  >(currentEmbeddingModel!);

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useSWR<SavedSearchSettings | null>(
      "/api/search-settings/get-current-search-settings",
      errorHandlingFetcher,
      { refreshInterval: 5000 } // 5 seconds
    );

  useEffect(() => {
    if (searchSettings) {
      setAdvancedEmbeddingDetails({
        index_name: searchSettings.index_name,
        multipass_indexing: searchSettings.multipass_indexing,
        multilingual_expansion: searchSettings.multilingual_expansion,
        disable_rerank_for_streaming:
          searchSettings.disable_rerank_for_streaming,
        num_rerank: searchSettings.num_rerank,
        api_url: null,
      });

      setRerankingDetails({
        rerank_api_key: searchSettings.rerank_api_key,
        rerank_provider_type: searchSettings.rerank_provider_type,
        rerank_model_name: searchSettings.rerank_model_name,
        rerank_api_url: searchSettings.rerank_api_url,
      });
    }
  }, [searchSettings]);

  const originalRerankingDetails: RerankingDetails = searchSettings
    ? {
        rerank_api_key: searchSettings.rerank_api_key,
        rerank_provider_type: searchSettings.rerank_provider_type,
        rerank_model_name: searchSettings.rerank_model_name,
        rerank_api_url: searchSettings.rerank_api_url,
      }
    : {
        rerank_api_key: "",
        rerank_provider_type: null,
        rerank_model_name: "",
        rerank_api_url: null,
      };

  useEffect(() => {
    if (currentEmbeddingModel) {
      setSelectedProvider(currentEmbeddingModel);
    }
  }, [currentEmbeddingModel]);

  const handleReindex = async () => {
    const update = await updateSearch();
    if (update) {
      await onConfirm();
    }
  };

  const needsReIndex =
    currentEmbeddingModel != selectedProvider ||
    searchSettings?.multipass_indexing !=
      advancedEmbeddingDetails.multipass_indexing;

  const updateSearch = useCallback(async () => {
    if (!selectedProvider) {
      return false;
    }
    const searchSettings = combineSearchSettings(
      selectedProvider,
      advancedEmbeddingDetails,
      rerankingDetails,
      selectedProvider.provider_type?.toLowerCase() as EmbeddingProvider | null
    );

    const response = await updateSearchSettings(searchSettings);
    if (response.ok) {
      return true;
    } else {
      setPopup({ message: "Failed to update search settings", type: "error" });
      return false;
    }
  }, [selectedProvider, advancedEmbeddingDetails, rerankingDetails, setPopup]);

  const ReIndexingButton = useMemo(() => {
    const ReIndexingButtonComponent = ({
      needsReIndex,
    }: {
      needsReIndex: boolean;
    }) => {
      return needsReIndex ? (
        <div className="flex mx-auto gap-x-1 ml-auto items-center">
          <button
            className="enabled:cursor-pointer disabled:bg-accent/50 disabled:cursor-not-allowed bg-agent flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
            onClick={handleReindex}
          >
            Re-index
          </button>
          <div className="relative group">
            <WarningCircle
              className="text-text-800 cursor-help"
              size={20}
              weight="fill"
            />
            <div className="absolute z-10 invisible group-hover:visible bg-background-800 text-text-200 text-sm rounded-md shadow-md p-2 right-0 mt-1 w-64">
              <p className="font-semibold mb-2">Needs re-indexing due to:</p>
              <ul className="list-disc pl-5">
                {currentEmbeddingModel != selectedProvider && (
                  <li>Changed embedding provider</li>
                )}
                {searchSettings?.multipass_indexing !=
                  advancedEmbeddingDetails.multipass_indexing && (
                  <li>Multipass indexing modification</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      ) : (
        <button
          className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 disabled:cursor-not-allowed bg-agent flex mx-auto gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
          onClick={async () => {
            updateSearch();
            navigateToEmbeddingPage("search settings");
          }}
        >
          Update Search
        </button>
      );
    };
    ReIndexingButtonComponent.displayName = "ReIndexingButton";
    return ReIndexingButtonComponent;
  }, [needsReIndex, updateSearch]);

  if (!selectedProvider) {
    return <ThreeDotsLoader />;
  }
  if (currentEmbeddingModelError || !currentEmbeddingModel) {
    return <ErrorCallout errorTitle="Failed to fetch embedding model status" />;
  }

  const updateCurrentModel = (newModel: string) => {
    setAdvancedEmbeddingDetails((values) => ({
      ...values,
      model_name: newModel,
    }));
  };

  const navigateToEmbeddingPage = (changedResource: string) => {
    router.push("/admin/configuration/search?message=search-settings");
  };

  const onConfirm = async () => {
    if (!selectedProvider) {
      return;
    }
    let searchSettings: SavedSearchSettings;

    if (selectedProvider.provider_type != null) {
      // This is a cloud model
      searchSettings = combineSearchSettings(
        selectedProvider,
        advancedEmbeddingDetails,
        rerankingDetails,
        selectedProvider.provider_type
          ?.toLowerCase()
          .split(" ")[0] as EmbeddingProvider | null
      );
    } else {
      // This is a locally hosted model
      searchSettings = combineSearchSettings(
        selectedProvider,
        advancedEmbeddingDetails,
        rerankingDetails,
        null
      );
    }

    searchSettings.index_name = null;

    const response = await fetch(
      "/api/search-settings/set-new-search-settings",
      {
        method: "POST",
        body: JSON.stringify(searchSettings),
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    if (response.ok) {
      navigateToEmbeddingPage("embedding model");
    } else {
      setPopup({ message: "Failed to update embedding model", type: "error" });

      alert(`Failed to update embedding model - ${await response.text()}`);
    }
  };

  return (
    <div className="mx-auto mb-8 w-full">
      {popup}

      <div className="mb-4">
        <HealthCheckBanner />
      </div>
      <div className="mx-auto max-w-4xl">
        {formStep == 0 && (
          <>
            <h2 className="text-2xl font-bold mb-4 text-text-800">
              Select an Embedding Model
            </h2>
            <Text className="mb-4">
              Note that updating the backing model will require a complete
              re-indexing of all documents across every connected source. This
              is taken care of in the background so that the system can continue
              to be used, but depending on the size of the corpus, this could
              take hours or days. You can monitor the progress of the
              re-indexing on this page while the models are being switched.
            </Text>
            <CardSection>
              <EmbeddingModelSelection
                updateCurrentModel={updateCurrentModel}
                setModelTab={setModelTab}
                modelTab={modelTab}
                selectedProvider={selectedProvider}
                currentEmbeddingModel={currentEmbeddingModel}
                updateSelectedProvider={updateSelectedProvider}
                advancedEmbeddingDetails={advancedEmbeddingDetails}
              />
            </CardSection>
            <div className="mt-4 flex w-full justify-end">
              <button
                className="enabled:cursor-pointer disabled:cursor-not-allowed disabled:bg-blue-200 bg-blue-400 flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                onClick={() => {
                  if (
                    selectedProvider.model_name.includes("e5") &&
                    displayPoorModelName
                  ) {
                    setDisplayPoorModelName(false);
                    setShowPoorModel(true);
                  } else {
                    nextFormStep();
                  }
                }}
              >
                Continue
                <ArrowRight />
              </button>
            </div>
          </>
        )}
        {showPoorModel && (
          <Modal
            onOutsideClick={() => setShowPoorModel(false)}
            width="max-w-3xl"
            title={`Are you sure you want to select ${selectedProvider.model_name}?`}
          >
            <>
              <div className="text-lg">
                {selectedProvider.model_name} is a lower accuracy model.
                <br />
                We recommend the following alternatives.
                <li>Cohere embed-english-v3.0 for cloud-based</li>
                <li>Nomic nomic-embed-text-v1 for self-hosted</li>
              </div>
              <div className="flex mt-4 justify-between">
                <Button
                  variant="secondary"
                  onClick={() => setShowPoorModel(false)}
                >
                  Cancel update
                </Button>
                <Button
                  onClick={() => {
                    setShowPoorModel(false);
                    nextFormStep();
                  }}
                >
                  Continue with {selectedProvider.model_name}
                </Button>
              </div>
            </>
          </Modal>
        )}

        {formStep == 1 && (
          <>
            <h2 className="text-2xl font-bold mb-4 text-text-800">
              Select a Reranking Model
            </h2>
            <Text className="mb-4">
              Updating the reranking model does not require re-indexing
              documents. The reranker helps improve search quality by reordering
              results after the initial embedding search. Changes will take
              effect immediately for all new searches.
            </Text>

            <CardSection>
              <RerankingDetailsForm
                setModelTab={setModelTab}
                modelTab={
                  originalRerankingDetails.rerank_model_name
                    ? modelTab
                    : modelTab || "cloud"
                }
                currentRerankingDetails={rerankingDetails}
                originalRerankingDetails={originalRerankingDetails}
                setRerankingDetails={setRerankingDetails}
              />
            </CardSection>

            <div className={`mt-4 w-full grid grid-cols-3`}>
              <button
                className="border-border-dark mr-auto border flex gap-x-1 items-center text-text p-2.5 text-sm font-regular rounded-sm "
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                Previous
              </button>

              <ReIndexingButton needsReIndex={needsReIndex} />

              <div className="flex w-full justify-end">
                <button
                  className={`enabled:cursor-pointer enabled:hover:underline disabled:cursor-not-allowed mt-auto enabled:text-text-600 disabled:text-text-400 ml-auto flex gap-x-1 items-center py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                  onClick={() => {
                    nextFormStep();
                  }}
                >
                  Advanced
                  <ArrowRight />
                </button>
              </div>
            </div>
          </>
        )}
        {formStep == 2 && (
          <>
            <h2 className="text-2xl font-bold mb-4 text-text-800">
              Advanced Search Configuration
            </h2>
            <Text className="mb-4">
              Configure advanced embedding and search settings. Changes will
              require re-indexing documents.
            </Text>

            <CardSection>
              <AdvancedEmbeddingFormPage
                advancedEmbeddingDetails={advancedEmbeddingDetails}
                updateAdvancedEmbeddingDetails={updateAdvancedEmbeddingDetails}
              />
            </CardSection>

            <div className={`mt-4 grid  grid-cols-3 w-full `}>
              <button
                className={`border-border-dark border mr-auto flex gap-x-1 
                  items-center text-text py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                Previous
              </button>

              <ReIndexingButton needsReIndex={needsReIndex} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
