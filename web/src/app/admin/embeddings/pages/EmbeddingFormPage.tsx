"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import { usePopup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { EmbeddingModelSelection } from "../EmbeddingModelSelectionForm";
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft,
  ArrowRight,
  WarningCircle,
  CaretDown,
  Warning,
} from "@phosphor-icons/react";
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
      embedding_precision: EmbeddingPrecision.FLOAT,
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
        message: i18n.t(k.FAILED_TO_UPDATE_SEARCH_SETTINGS),
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
          <div className="flex items-center">
            <button
              onClick={() => {
                if (reindexType == ReindexType.INSTANT) {
                  setShowInstantSwitchConfirm(true);
                } else {
                  handleReIndex();
                  navigateToEmbeddingPage(i18n.t(k.SEARCH_SETTINGS1));
                }
              }}
              disabled={!isOverallFormValid}
              className="
                enabled:cursor-pointer 
                disabled:bg-accent/50 
                disabled:cursor-not-allowed 
                bg-agent 
                flex 
                items-center 
                justify-center
                text-white 
                text-sm 
                font-regular 
                rounded-l-sm
                py-2.5 
                px-3.5
                transition-colors
                hover:bg-white/10
                text-center
                w-32"
            >
              {reindexType == ReindexType.REINDEX
                ? i18n.t(k.RE_INDEX1)
                : i18n.t(k.INSTANT_SWITCH)}
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  disabled={!isOverallFormValid}
                  className="
                    enabled:cursor-pointer 
                    disabled:bg-accent/50 
                    disabled:cursor-not-allowed 
                    bg-agent 
                    flex 
                    items-center 
                    justify-center
                    text-white 
                    text-sm 
                    font-regular 
                    rounded-r-sm
                    border-l
                    border-white/20
                    py-2.5 
                    px-2
                    h-[40px]
                    w-[34px]
                    transition-colors
                    hover:bg-white/10"
                >
                  <CaretDown className="h-4 w-4" />
                </button>
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
                        {i18n.t(k.RECOMMENDED_RE_INDEX)}
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{i18n.t(k.RE_RUNS_ALL_CONNECTORS_IN_THE)}</p>
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
                        {i18n.t(k.INSTANT_SWITCH)}
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{i18n.t(k.IMMEDIATELY_SWITCHES_TO_NEW_SE)}</p>
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
                <p className="font-semibold mb-2">
                  {i18n.t(k.NEEDS_RE_INDEXING_DUE_TO)}
                </p>
                <ul className="list-disc pl-5">
                  {currentEmbeddingModel != selectedProvider && (
                    <li>{i18n.t(k.CHANGED_EMBEDDING_PROVIDER)}</li>
                  )}
                  {searchSettings?.multipass_indexing !=
                    advancedEmbeddingDetails.multipass_indexing && (
                    <li>{i18n.t(k.MULTIPASS_INDEXING_MODIFICATIO)}</li>
                  )}
                  {searchSettings?.embedding_precision !=
                    advancedEmbeddingDetails.embedding_precision && (
                    <li>{i18n.t(k.EMBEDDING_PRECISION_MODIFICATI)}</li>
                  )}
                  {searchSettings?.reduced_dimension !=
                    advancedEmbeddingDetails.reduced_dimension && (
                    <li>{i18n.t(k.REDUCED_DIMENSION_MODIFICATION)}</li>
                  )}
                  {(searchSettings?.enable_contextual_rag !=
                    advancedEmbeddingDetails.enable_contextual_rag ||
                    searchSettings?.contextual_rag_llm_name !=
                      advancedEmbeddingDetails.contextual_rag_llm_name ||
                    searchSettings?.contextual_rag_llm_provider !=
                      advancedEmbeddingDetails.contextual_rag_llm_provider) && (
                    <li>{i18n.t(k.CONTEXTUAL_RAG_MODIFICATION)}</li>
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
                  <p className="font-semibold mb-2">
                    {i18n.t(k.VALIDATION_ERRORS)}
                  </p>
                  <ul className="list-disc pl-5">
                    {Object.entries(combinedFormErrors).map(
                      ([field, error]) => (
                        <li key={field}>
                          {field}
                          {i18n.t(k._2)} {error}
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
          <button
            className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 disabled:cursor-not-allowed bg-agent flex mx-auto gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
            onClick={() => {
              updateSearch();
              navigateToEmbeddingPage(i18n.t(k.SEARCH_SETTINGS1));
            }}
            disabled={!isOverallFormValid}
          >
            {i18n.t(k.UPDATE_SEARCH)}
          </button>
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
                    {i18n.t(k.VALIDATION_ERRORS)}
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
    return (
      <ErrorCallout errorTitle={i18n.t(k.FAILED_TO_GET_EMBEDDING_STATUS)} />
    );
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
      setPopup({
        message: i18n.t(k.FAILED_TO_UPDATE_EMBEDDING_MODEL),
        type: "error",
      });

      alert(
        i18n.t(k.FAILED_TO_UPDATE_EMBEDDING_MODEL_ALERT, {
          response: await response.text(),
        })
      );
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
              {i18n.t(k.SELECT_AN_EMBEDDING_MODEL)}
            </h2>
            <Text className="mb-4">
              {i18n.t(k.NOTE_THAT_UPDATING_THE_BACKING)}
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
                {i18n.t(k.CONTINUE)}
                <ArrowRight />
              </button>
            </div>
          </>
        )}
        {showPoorModel && (
          <Modal
            onOutsideClick={() => setShowPoorModel(false)}
            width="max-w-3xl"
            title={`${i18n.t(k.ARE_YOU_SURE_YOU_WANT_TO_SELEC)} ${
              selectedProvider.model_name
            }${i18n.t(k._10)}`}
          >
            <>
              <div className="text-lg">
                {selectedProvider.model_name}{" "}
                {i18n.t(k.IS_A_LOWER_ACCURACY_MODEL)}
                <br />
                {i18n.t(k.WE_RECOMMEND_THE_FOLLOWING_ALT)}
                <li>{i18n.t(k.COHERE_EMBED_ENGLISH_V_FOR)}</li>
                <li>{i18n.t(k.NOMIC_NOMIC_EMBED_TEXT_V_FOR)}</li>
              </div>
              <div className="flex mt-4 justify-between">
                <Button
                  variant="secondary"
                  onClick={() => setShowPoorModel(false)}
                >
                  {i18n.t(k.CANCEL_UPDATE)}
                </Button>
                <Button
                  onClick={() => {
                    setShowPoorModel(false);
                    nextFormStep();
                  }}
                >
                  {i18n.t(k.CONTINUE_WITH)} {selectedProvider.model_name}
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
              {i18n.t(k.SELECT_A_RERANKING_MODEL)}
            </h2>
            <Text className="mb-4">
              {i18n.t(k.UPDATING_THE_RERANKING_MODEL_D)}
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
              <button
                className="border-border-dark mr-auto border flex gap-x-1 items-center text-text p-2.5 text-sm font-regular rounded-sm "
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                {i18n.t(k.PREVIOUS)}
              </button>

              <ReIndexingButton needsReIndex={needsReIndex} />

              <div className="flex w-full justify-end">
                <button
                  className={`enabled:cursor-pointer enabled:hover:underline disabled:cursor-not-allowed mt-auto enabled:text-text-600 disabled:text-text-400 ml-auto flex gap-x-1 items-center py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                  onClick={() => {
                    nextFormStep();
                  }}
                >
                  {i18n.t(k.ADVANCED)}
                  <ArrowRight />
                </button>
              </div>
            </div>
          </>
        )}
        {formStep == 2 && (
          <>
            <h2 className="text-2xl font-bold mb-4 text-text-800">
              {i18n.t(k.ADVANCED_SEARCH_CONFIGURATION)}
            </h2>
            <Text className="mb-4">
              {i18n.t(k.CONFIGURE_ADVANCED_EMBEDDING_A)}
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
              <button
                className={`border-border-dark border mr-auto flex gap-x-1 
                  items-center text-text py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                {i18n.t(k.PREVIOUS)}
              </button>

              <ReIndexingButton needsReIndex={needsReIndex} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
