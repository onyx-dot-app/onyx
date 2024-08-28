"use client";
import { usePopup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { EmbeddingModelSelection } from "../EmbeddingModelSelectionForm";
import { useEffect, useState } from "react";
import { Button, Card, Text } from "@tremor/react";
import { ArrowLeft, ArrowRight, WarningCircle } from "@phosphor-icons/react";
import {
  CloudEmbeddingModel,
  EmbeddingModelDescriptor,
  HostedEmbeddingModel,
} from "../../../../components/embedding/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import AdvancedEmbeddingFormPage from "./AdvancedEmbeddingFormPage";
import {
  AdvancedDetails,
  RerankingDetails,
  SavedSearchSettings,
} from "../interfaces";
import RerankingDetailsForm from "../RerankingFormPage";
import { useEmbeddingFormContext } from "@/components/context/EmbeddingContext";
import { Modal } from "@/components/Modal";

export default function EmbeddingForm() {
  const { formStep, nextFormStep, prevFormStep } = useEmbeddingFormContext();
  const { popup, setPopup } = usePopup();

  const [advancedEmbeddingDetails, setAdvancedEmbeddingDetails] =
    useState<AdvancedDetails>({
      disable_rerank_for_streaming: false,
      multilingual_expansion: [],
      multipass_indexing: true,
    });

  const [rerankingDetails, setRerankingDetails] = useState<RerankingDetails>({
    api_key: "",
    num_rerank: 0,
    provider_type: null,
    rerank_model_name: "",
  });

  const updateAdvancedEmbeddingDetails = (
    key: keyof AdvancedDetails,
    value: any
  ) => {
    setAdvancedEmbeddingDetails((values) => ({ ...values, [key]: value }));
  };

  async function updateSearchSettings(searchSettings: SavedSearchSettings) {
    const response = await fetch(
      "/api/search-settings/update-search-settings",
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
    "/api/search-settings/get-current-embedding-model",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const [selectedProvider, setSelectedProvider] = useState<
    CloudEmbeddingModel | HostedEmbeddingModel | null
  >(currentEmbeddingModel!);

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useSWR<SavedSearchSettings | null>(
      "/api/search-settings/get-search-settings",
      errorHandlingFetcher,
      { refreshInterval: 5000 } // 5 seconds
    );

  useEffect(() => {
    if (searchSettings) {
      setAdvancedEmbeddingDetails({
        disable_rerank_for_streaming:
          searchSettings.disable_rerank_for_streaming,
        multilingual_expansion: searchSettings.multilingual_expansion,
        multipass_indexing: searchSettings.multipass_indexing,
      });
      setRerankingDetails({
        api_key: searchSettings.api_key,
        num_rerank: searchSettings.num_rerank,
        provider_type: searchSettings.provider_type,
        rerank_model_name: searchSettings.rerank_model_name,
      });
    }
  }, [searchSettings]);

  const originalRerankingDetails = searchSettings
    ? {
        api_key: searchSettings.api_key,
        num_rerank: searchSettings.num_rerank,
        provider_type: searchSettings.provider_type,
        rerank_model_name: searchSettings.rerank_model_name,
      }
    : {
        api_key: "",
        num_rerank: 0,
        provider_type: null,
        rerank_model_name: "",
      };

  useEffect(() => {
    if (currentEmbeddingModel) {
      setSelectedProvider(currentEmbeddingModel);
    }
  }, [currentEmbeddingModel]);

  useEffect(() => {
    if (currentEmbeddingModel) {
      setSelectedProvider(currentEmbeddingModel);
    }
  }, [currentEmbeddingModel]);
  if (!selectedProvider) {
    return <ThreeDotsLoader />;
  }
  if (currentEmbeddingModelError || !currentEmbeddingModel) {
    return <ErrorCallout errorTitle="Failed to fetch embedding model status" />;
  }

  const updateSearch = async () => {
    let values: SavedSearchSettings = {
      ...rerankingDetails,
      ...advancedEmbeddingDetails,
    };
    const response = await updateSearchSettings(values);
    if (response.ok) {
      setPopup({
        message: "Updated search settings succesffuly",
        type: "success",
      });
      mutate("/api/search-settings/get-search-settings");
      return true;
    } else {
      setPopup({ message: "Failed to update search settings", type: "error" });
      return false;
    }
  };

  const onConfirm = async () => {
    let newModel: EmbeddingModelDescriptor;

    if ("provider_type" in selectedProvider) {
      // This is a CloudEmbeddingModel
      newModel = {
        ...selectedProvider,
        model_name: selectedProvider.model_name,
        provider_type: selectedProvider.provider_type
          ?.toLowerCase()
          .split(" ")[0],
      };
    } else {
      // This is an EmbeddingModelDescriptor
      newModel = {
        ...selectedProvider,
        model_name: selectedProvider.model_name!,
        description: "",
        provider_type: null,
      };
    }

    const response = await fetch(
      "/api/search-settings/set-new-embedding-model",
      {
        method: "POST",
        body: JSON.stringify(newModel),
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
    if (response.ok) {
      setPopup({
        message: "Changed provider suceessfully. Redirecing to embedding page",
        type: "success",
      });
      mutate("/api/search-settings/get-secondary-embedding-model");
      setTimeout(() => {
        window.open("/admin/configuration/search", "_self");
      }, 2000);
    } else {
      setPopup({ message: "Failed to update embedding model", type: "error" });

      alert(`Failed to update embedding model - ${await response.text()}`);
    }
  };

  const needsReIndex =
    currentEmbeddingModel != selectedProvider ||
    searchSettings?.multipass_indexing !=
      advancedEmbeddingDetails.multipass_indexing;

  const ReIndxingButton = () => {
    return (
      <div className="flex mx-auto gap-x-1 ml-auto items-center">
        <button
          className="enabled:cursor-pointer disabled:bg-accent/50 disabled:cursor-not-allowed bg-accent flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
          onClick={async () => {
            const updated = await updateSearch();
            if (updated) {
              await onConfirm();
            }
          }}
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
    );
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
            <Card>
              <EmbeddingModelSelection
                setModelTab={setModelTab}
                modelTab={modelTab}
                selectedProvider={selectedProvider}
                currentEmbeddingModel={currentEmbeddingModel}
                updateSelectedProvider={updateSelectedProvider}
              />
            </Card>
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
                <Button color="green" onClick={() => setShowPoorModel(false)}>
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
            <Card>
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
            </Card>

            <div className={` mt-4 w-full grid grid-cols-3`}>
              <button
                className="border-border-dark mr-auto border flex gap-x-1 items-center text-text p-2.5 text-sm font-regular rounded-sm "
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                Previous
              </button>

              {needsReIndex ? (
                <ReIndxingButton />
              ) : (
                <button
                  className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 disabled:cursor-not-allowed bg-accent flex mx-auto gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                  onClick={async () => {
                    updateSearch();
                  }}
                >
                  Update Search
                </button>
              )}

              <div className="flex w-full justify-end">
                <button
                  className={`enabled:cursor-pointer enabled:hover:underline disabled:cursor-not-allowed mt-auto enabled:text-text-600 disabled:text-text-400 ml-auto flex gap-x-1 items-center py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                  // disabled={!isFormValid}
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
            <Card>
              <AdvancedEmbeddingFormPage
                numRerank={rerankingDetails.num_rerank}
                setRerankingDetails={setRerankingDetails}
                advancedEmbeddingDetails={advancedEmbeddingDetails}
                updateAdvancedEmbeddingDetails={updateAdvancedEmbeddingDetails}
              />
            </Card>

            <div className={`mt-4 grid  grid-cols-3 w-full `}>
              <button
                className={`border-border-dark border mr-auto flex gap-x-1 
                  items-center text-text py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                Previous
              </button>

              {needsReIndex ? (
                <ReIndxingButton />
              ) : (
                <button
                  className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 
                    disabled:cursor-not-allowed bg-accent flex mx-auto gap-x-1 items-center 
                    text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                  onClick={async () => {
                    updateSearch();
                  }}
                >
                  Update Search
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
