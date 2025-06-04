"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { Dispatch, SetStateAction, useState } from "react";
import {
  CloudEmbeddingProvider,
  CloudEmbeddingModel,
  AVAILABLE_MODELS,
  HostedEmbeddingModel,
  EmbeddingProvider,
} from "../../../components/embedding/interfaces";
import OpenEmbeddingPage from "./pages/OpenEmbeddingPage";
import CloudEmbeddingPage from "./pages/CloudEmbeddingPage";
import { ProviderCreationModal } from "./modals/ProviderCreationModal";

import { DeleteCredentialsModal } from "./modals/DeleteCredentialsModal";
import { SelectModelModal } from "./modals/SelectModelModal";
import { ChangeCredentialsModal } from "./modals/ChangeCredentialsModal";
import { ModelSelectionConfirmationModal } from "./modals/ModelSelectionModal";
import { AlreadyPickedModal } from "./modals/AlreadyPickedModal";
import { ModelOption } from "../../../components/embedding/ModelSelector";
import {
  EMBEDDING_MODELS_ADMIN_URL,
  EMBEDDING_PROVIDERS_ADMIN_URL,
} from "../configuration/llm/constants";
import { AdvancedSearchConfiguration } from "./interfaces";

export interface EmbeddingDetails {
  api_key?: string;
  api_url?: string;
  api_version?: string;
  deployment_name?: string;
  custom_config: any;
  provider_type: EmbeddingProvider;
}

export function EmbeddingModelSelection({
  selectedProvider,
  currentEmbeddingModel,
  updateSelectedProvider,
  modelTab,
  setModelTab,
  updateCurrentModel,
  advancedEmbeddingDetails,
}: {
  modelTab: "open" | "cloud" | null;
  setModelTab: Dispatch<SetStateAction<"open" | "cloud" | null>>;
  currentEmbeddingModel: CloudEmbeddingModel | HostedEmbeddingModel;
  selectedProvider: CloudEmbeddingModel | HostedEmbeddingModel;
  updateSelectedProvider: (
    model: CloudEmbeddingModel | HostedEmbeddingModel
  ) => void;
  updateCurrentModel: (
    newModel: string,
    provider_type: EmbeddingProvider
  ) => void;
  advancedEmbeddingDetails: AdvancedSearchConfiguration;
}) {
  // Cloud Provider based modals
  const [showTentativeProvider, setShowTentativeProvider] =
    useState<CloudEmbeddingProvider | null>(null);

  const [showUnconfiguredProvider, setShowUnconfiguredProvider] =
    useState<CloudEmbeddingProvider | null>(null);
  const [changeCredentialsProvider, setChangeCredentialsProvider] =
    useState<CloudEmbeddingProvider | null>(null);

  // Cloud Model based modals
  const [alreadySelectedModel, setAlreadySelectedModel] =
    useState<CloudEmbeddingModel | null>(null);
  const [showTentativeModel, setShowTentativeModel] =
    useState<CloudEmbeddingModel | null>(null);

  const [showModelInQueue, setShowModelInQueue] =
    useState<CloudEmbeddingModel | null>(null);

  // Open Model based modals
  const [showTentativeOpenProvider, setShowTentativeOpenProvider] =
    useState<HostedEmbeddingModel | null>(null);

  const [showDeleteCredentialsModal, setShowDeleteCredentialsModal] =
    useState<boolean>(false);

  const [showAddConnectorPopup, setShowAddConnectorPopup] =
    useState<boolean>(false);

  const { data: embeddingModelDetails } = useSWR<CloudEmbeddingModel[]>(
    EMBEDDING_MODELS_ADMIN_URL,
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const {
    data: embeddingProviderDetails,
    mutate: mutateEmbeddingProviderDetails,
  } = useSWR<EmbeddingDetails[]>(
    EMBEDDING_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  return (
    <div className="p-2">
      {alreadySelectedModel && (
        <AlreadyPickedModal
          model={alreadySelectedModel}
          onClose={() => setAlreadySelectedModel(null)}
        />
      )}

      {showTentativeOpenProvider && (
        <ModelSelectionConfirmationModal
          selectedModel={showTentativeOpenProvider}
          isCustom={
            AVAILABLE_MODELS.find(
              (model) =>
                model.model_name === showTentativeOpenProvider.model_name
            ) === undefined
          }
          onConfirm={() => {
            updateSelectedProvider(showTentativeOpenProvider);
            setShowTentativeOpenProvider(null);
          }}
          onCancel={() => setShowTentativeOpenProvider(null)}
        />
      )}

      {showTentativeProvider && (
        <ProviderCreationModal
          updateCurrentModel={updateCurrentModel}
          isProxy={
            showTentativeProvider.provider_type == EmbeddingProvider.LITELLM
          }
          isAzure={
            showTentativeProvider.provider_type == EmbeddingProvider.AZURE
          }
          selectedProvider={showTentativeProvider}
          onConfirm={() => {
            setShowTentativeProvider(showUnconfiguredProvider);
            if (showModelInQueue) {
              setShowTentativeModel(showModelInQueue);
            }
            mutateEmbeddingProviderDetails();
          }}
          onCancel={() => {
            setShowModelInQueue(null);
            setShowTentativeProvider(null);
          }}
        />
      )}

      {changeCredentialsProvider && (
        <ChangeCredentialsModal
          isProxy={
            changeCredentialsProvider.provider_type == EmbeddingProvider.LITELLM
          }
          isAzure={
            changeCredentialsProvider.provider_type == EmbeddingProvider.AZURE
          }
          useFileUpload={
            changeCredentialsProvider.provider_type == EmbeddingProvider.GOOGLE
          }
          onDeleted={() => {
            setChangeCredentialsProvider(null);
            mutateEmbeddingProviderDetails();
          }}
          provider={changeCredentialsProvider}
          onConfirm={() => setChangeCredentialsProvider(null)}
          onCancel={() => setChangeCredentialsProvider(null)}
        />
      )}

      {showTentativeModel && (
        <SelectModelModal
          model={showTentativeModel}
          onConfirm={() => {
            setShowModelInQueue(null);
            updateSelectedProvider(showTentativeModel);
            setShowTentativeModel(null);
          }}
          onCancel={() => {
            setShowModelInQueue(null);
            setShowTentativeModel(null);
          }}
        />
      )}

      {showDeleteCredentialsModal && (
        <DeleteCredentialsModal
          modelProvider={showTentativeProvider!}
          onConfirm={() => {
            setShowDeleteCredentialsModal(false);
            mutateEmbeddingProviderDetails();
          }}
          onCancel={() => setShowDeleteCredentialsModal(false)}
        />
      )}

      <p className="mb-4">
        Select from cloud, self-hosted models, or continue with your current
        embedding model.
      </p>
      <div className="text-sm mr-auto mb-6 divide-x-2 flex">
        <button
          onClick={() => setModelTab(null)}
          className={`mr-4 p-2 font-bold  ${
            !modelTab
              ? "rounded bg-neutral-900 dark:bg-neutral-950 text-neutral-100 dark:text-neutral-300 underline"
              : " hover:underline bg-neutral-100 dark:bg-neutral-900"
          }`}
        >
          Current
        </button>
        <div className="px-2">
          <button
            onClick={() => setModelTab("cloud")}
            className={`mx-2 p-2 font-bold  ${
              modelTab == "cloud"
                ? "rounded bg-neutral-900 dark:bg-neutral-950 text-neutral-100 dark:text-neutral-300 underline"
                : " hover:underline bg-neutral-100 dark:bg-neutral-900"
            }`}
          >
            Cloud-based
          </button>
        </div>
        <div className="px-2">
          <button
            onClick={() => setModelTab("open")}
            className={` mx-2 p-2 font-bold  ${
              modelTab == "open"
                ? "rounded bg-neutral-900 dark:bg-neutral-950 text-neutral-100 dark:text-neutral-300 underline"
                : "hover:underline bg-neutral-100 dark:bg-neutral-900"
            }`}
          >
            Self-hosted
          </button>
        </div>
      </div>

      {modelTab == "open" && (
        <OpenEmbeddingPage
          selectedProvider={selectedProvider}
          onSelectOpenSource={(model: HostedEmbeddingModel) => {
            setShowTentativeOpenProvider(model);
          }}
        />
      )}

      {modelTab == "cloud" && (
        <CloudEmbeddingPage
          advancedEmbeddingDetails={advancedEmbeddingDetails}
          embeddingModelDetails={embeddingModelDetails}
          setShowModelInQueue={setShowModelInQueue}
          setShowTentativeModel={setShowTentativeModel}
          currentModel={selectedProvider || currentEmbeddingModel}
          setAlreadySelectedModel={setAlreadySelectedModel}
          embeddingProviderDetails={embeddingProviderDetails}
          setShowTentativeProvider={setShowTentativeProvider}
          setChangeCredentialsProvider={setChangeCredentialsProvider}
        />
      )}

      {!modelTab && (
        <>
          <button onClick={() => updateSelectedProvider(currentEmbeddingModel)}>
            <ModelOption
              model={currentEmbeddingModel}
              selected={
                selectedProvider.model_name == currentEmbeddingModel.model_name
              }
            />
          </button>
        </>
      )}
    </div>
  );
}
