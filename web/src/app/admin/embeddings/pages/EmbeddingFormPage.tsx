"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { EmbeddingModelSelection } from "../EmbeddingModelSelectionForm";
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import Text from "@/components/ui/text";
import Button from "@/refresh-components/buttons/Button";
import { WarningCircle, Warning, CaretDownIcon } from "@phosphor-icons/react";
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
  EmbeddingPrecision,
  RerankingDetails,
  SavedSearchSettings,
} from "../interfaces";
import RerankingDetailsForm from "../RerankingFormPage";
import { useEmbeddingFormContext } from "@/components/context/EmbeddingContext";
import { Modal } from "@/components/Modal";
import { InstantSwitchConfirmModal } from "../modals/InstantSwitchConfirmModal";

import { useRouter } from "next/navigation";
import CardSection from "@/components/admin/CardSection";
import { combineSearchSettings } from "./utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import SvgArrowLeft from "@/icons/arrow-left";
import SvgArrowRight from "@/icons/arrow-right";

enum ReindexType {
  REINDEX = "reindex",
  INSTANT = "instant",
}

export default function EmbeddingForm() {
  const { formStep, nextFormStep, prevFormStep } = useEmbeddingFormContext();
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const [advancedEmbeddingDetails, setAdvancedEmbeddingDetails] =
    useState<AdvancedSearchConfiguration>({
      index_name: "",
      multipass_indexing: true,
      enable_contextual_rag: false,
      contextual_rag_llm_name: null,
      contextual_rag_llm_provider: null,
      multilingual_expansion: [],
      disable_rerank_for_streaming: false,
      api_url: null,
      num_rerank: 0,
      embedding_precision: EmbeddingPrecision.BFLOAT16,
      reduced_dimension: null,
    });

  const [rerankingDetails, setRerankingDetails] = useState<RerankingDetails>({
    rerank_api_key: "",
    rerank_provider_type: null,
    rerank_model_name: "",
    rerank_api_url: null,
  });

  const [reindexType, setReindexType] = useState<ReindexType>(
    ReindexType.REINDEX
  );

  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [isFormValid, setIsFormValid] = useState(true);
  const [rerankFormErrors, setRerankFormErrors] = useState<
    Record<string, string>
  >({});
  const [isRerankFormValid, setIsRerankFormValid] = useState(true);
  const advancedFormRef = useRef(null);
  const rerankFormRef = useRef(null);

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
  const [showInstantSwitchConfirm, setShowInstantSwitchConfirm] =
    useState(false);
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
        enable_contextual_rag: searchSettings.enable_contextual_rag,
        contextual_rag_llm_name: searchSettings.contextual_rag_llm_name,
        contextual_rag_llm_provider: searchSettings.contextual_rag_llm_provider,
        multilingual_expansion: searchSettings.multilingual_expansion,
        disable_rerank_for_streaming:
          searchSettings.disable_rerank_for_streaming,
        num_rerank: searchSettings.num_rerank,
        api_url: null,
        embedding_precision: searchSettings.embedding_precision,
        reduced_dimension: searchSettings.reduced_dimension,
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

  const needsReIndex =
    currentEmbeddingModel != selectedProvider ||
    searchSettings?.multipass_indexing !=
      advancedEmbeddingDetails.multipass_indexing ||
    searchSettings?.embedding_precision !=
      advancedEmbeddingDetails.embedding_precision ||
    searchSettings?.reduced_dimension !=
      advancedEmbeddingDetails.reduced_dimension ||
    searchSettings?.enable_contextual_rag !=
      advancedEmbeddingDetails.enable_contextual_rag;

  const updateSearch = useCallback(async () => {
    if (!selectedProvider) {
      return false;
    }
    const searchSettings = combineSearchSettings(
      selectedProvider,
      advancedEmbeddingDetails,
      rerankingDetails,
      selectedProvider.provider_type?.toLowerCase() as EmbeddingProvider | null,
      reindexType === ReindexType.REINDEX
    );

    const response = await updateSearchSettings(searchSettings);
    if (response.ok) {
      return true;
    } else {
      setPopup({
        message: "Failed to update search settings",
        type: "error",
      });
      return false;
    }
  }, [selectedProvider, advancedEmbeddingDetails, rerankingDetails, setPopup]);

  const handleValidationChange = useCallback(
    (isValid: boolean, errors: Record<string, string>) => {
      setIsFormValid(isValid);
      setFormErrors(errors);
    },
    []
  );

  const handleRerankValidationChange = useCallback(
    (isValid: boolean, errors: Record<string, string>) => {
      setIsRerankFormValid(isValid);
      setRerankFormErrors(errors);
    },
    []
  );

  // Combine validation states for both forms
  const isOverallFormValid = isFormValid && isRerankFormValid;
  const combinedFormErrors = useMemo(() => {
    return { ...formErrors, ...rerankFormErrors };
  }, [formErrors, rerankFormErrors]);

  const ReIndexingButton = useMemo(() => {
    const ReIndexingButtonComponent = ({
      needsReIndex,
    }: {
      needsReIndex: boolean;
    }) => {
      return needsReIndex ? (
        <div className="flex mx-auto gap-x-1 ml-auto items-center">
          <div className="flex items-center h-fit">
            <Button
              onClick={() => {
                if (reindexType == ReindexType.INSTANT) {
                  setShowInstantSwitchConfirm(true);
                } else {
                  handleReIndex();
                  navigateToEmbeddingPage("search settings");
                }
              }}
              disabled={!isOverallFormValid}
              action
              className="rounded-r-none w-32 h-full"
            >
              {reindexType == ReindexType.REINDEX
                ? "Re-index"
                : "Instant Switch"}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  disabled={!isOverallFormValid}
                  action
                  className="rounded-l-none border-l border-white/20 px-1 h-[36px] w-[30px] min-w-[30px]"
                >
                  <CaretDownIcon className="text-text-inverted-05" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem
                  onClick={() => {
                    setReindexType(ReindexType.REINDEX);
                  }}
                >
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger className="w-full text-left">
                        (Recommended) Re-index
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>
                          Re-runs all connectors in the background before
                          switching over. Takes longer but ensures no
                          degredation of search during the switch.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    setReindexType(ReindexType.INSTANT);
                  }}
                >
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger className="w-full text-left">
                        Instant Switch
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>
                          Immediately switches to new settings without
                          re-indexing. Searches will be degraded until the
                          re-indexing is complete.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {isOverallFormValid && (
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
                  {searchSettings?.embedding_precision !=
                    advancedEmbeddingDetails.embedding_precision && (
                    <li>Embedding precision modification</li>
                  )}
                  {searchSettings?.reduced_dimension !=
                    advancedEmbeddingDetails.reduced_dimension && (
                    <li>Reduced dimension modification</li>
                  )}
                  {(searchSettings?.enable_contextual_rag !=
                    advancedEmbeddingDetails.enable_contextual_rag ||
                    searchSettings?.contextual_rag_llm_name !=
                      advancedEmbeddingDetails.contextual_rag_llm_name ||
                    searchSettings?.contextual_rag_llm_provider !=
                      advancedEmbeddingDetails.contextual_rag_llm_provider) && (
                    <li>Contextual RAG modification</li>
                  )}
                </ul>
              </div>
            </div>
          )}
          {!isOverallFormValid &&
            Object.keys(combinedFormErrors).length > 0 && (
              <div className="relative group">
                <Warning
                  className="text-red-500 cursor-help"
                  size={20}
                  weight="fill"
                />
                <div className="absolute z-10 invisible group-hover:visible bg-background-800 text-text-200 text-sm rounded-md shadow-md p-2 right-0 mt-1 w-64">
                  <p className="font-semibold mb-2">Validation Errors:</p>
                  <ul className="list-disc pl-5">
                    {Object.entries(combinedFormErrors).map(
                      ([field, error]) => (
                        <li key={field}>
                          {field}: {error}
                        </li>
                      )
                    )}
                  </ul>
                </div>
              </div>
            )}
        </div>
      ) : (
        <div className="flex mx-auto gap-x-1 ml-auto items-center">
          <Button
            onClick={() => {
              updateSearch();
              navigateToEmbeddingPage("search settings");
            }}
            disabled={!isOverallFormValid}
          >
            Update Search
          </Button>
          {!isOverallFormValid &&
            Object.keys(combinedFormErrors).length > 0 && (
              <div className="relative group">
                <Warning
                  className="text-red-500 cursor-help"
                  size={20}
                  weight="fill"
                />
                <div className="absolute z-10 invisible group-hover:visible bg-background-800 text-text-200 text-sm rounded-md shadow-md p-2 right-0 mt-1 w-64">
                  <p className="font-semibold mb-2 text-red-400">
                    Validation Errors:
                  </p>
                  <ul className="list-disc pl-5">
                    {Object.entries(combinedFormErrors).map(
                      ([field, error]) => (
                        <li key={field}>{error}</li>
                      )
                    )}
                  </ul>
                </div>
              </div>
            )}
        </div>
      );
    };
    ReIndexingButtonComponent.displayName = "ReIndexingButton";
    return ReIndexingButtonComponent;
  }, [needsReIndex, reindexType, isOverallFormValid, combinedFormErrors]);

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

  const handleReIndex = async () => {
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
          .split(" ")[0] as EmbeddingProvider | null,
        reindexType === ReindexType.REINDEX
      );
    } else {
      // This is a locally hosted model
      searchSettings = combineSearchSettings(
        selectedProvider,
        advancedEmbeddingDetails,
        rerankingDetails,
        null,
        reindexType === ReindexType.REINDEX
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
              <Button
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
                rightIcon={SvgArrowRight}
                action
              >
                Continue
              </Button>
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
                <Button secondary onClick={() => setShowPoorModel(false)}>
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

        {showInstantSwitchConfirm && (
          <InstantSwitchConfirmModal
            onClose={() => setShowInstantSwitchConfirm(false)}
            onConfirm={() => {
              setShowInstantSwitchConfirm(false);
              handleReIndex();
              navigateToEmbeddingPage("search settings");
            }}
          />
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
                ref={rerankFormRef}
                setModelTab={setModelTab}
                modelTab={
                  originalRerankingDetails.rerank_model_name
                    ? modelTab
                    : modelTab || "cloud"
                }
                currentRerankingDetails={rerankingDetails}
                originalRerankingDetails={originalRerankingDetails}
                setRerankingDetails={setRerankingDetails}
                onValidationChange={handleRerankValidationChange}
              />
            </CardSection>

            <div className={`mt-4 w-full grid grid-cols-3`}>
              <Button
                leftIcon={SvgArrowLeft}
                onClick={() => prevFormStep()}
                secondary
              >
                Previous
              </Button>

              <ReIndexingButton needsReIndex={needsReIndex} />

              <div className="flex w-full justify-end">
                <Button
                  onClick={() => {
                    nextFormStep();
                  }}
                  rightIcon={SvgArrowRight}
                  secondary
                >
                  Advanced
                </Button>
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
                ref={advancedFormRef}
                advancedEmbeddingDetails={advancedEmbeddingDetails}
                updateAdvancedEmbeddingDetails={updateAdvancedEmbeddingDetails}
                embeddingProviderType={selectedProvider.provider_type}
                onValidationChange={handleValidationChange}
              />
            </CardSection>

            <div className={`mt-4 grid  grid-cols-3 w-full `}>
              <Button
                onClick={() => prevFormStep()}
                leftIcon={SvgArrowLeft}
                secondary
              >
                Previous
              </Button>

              <ReIndexingButton needsReIndex={needsReIndex} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
