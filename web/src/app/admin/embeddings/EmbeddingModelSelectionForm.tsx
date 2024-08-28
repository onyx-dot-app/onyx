"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { Dispatch, SetStateAction, useState } from "react";
import {
  CloudEmbeddingProvider,
  CloudEmbeddingModel,
  AVAILABLE_CLOUD_PROVIDERS,
  AVAILABLE_MODELS,
  INVALID_OLD_MODEL,
  HostedEmbeddingModel,
  EmbeddingModelDescriptor,
  EmbeddingProvider,
} from "../../../components/embedding/interfaces";
import { Connector } from "@/lib/connectors/connectors";
import OpenEmbeddingPage from "./pages/OpenEmbeddingPage";
import CloudEmbeddingPage from "./pages/CloudEmbeddingPage";
import { ProviderCreationModal } from "./modals/ProviderCreationModal";

import { DeleteCredentialsModal } from "./modals/DeleteCredentialsModal";
import { SelectModelModal } from "./modals/SelectModelModal";
import { ChangeCredentialsModal } from "./modals/ChangeCredentialsModal";
import { ModelSelectionConfirmationModal } from "./modals/ModelSelectionModal";
import { AlreadyPickedModal } from "./modals/AlreadyPickedModal";
import { ModelOption } from "../../../components/embedding/ModelSelector";
import { EMBEDDING_PROVIDERS_ADMIN_URL } from "../configuration/llm/constants";

export interface EmbeddingDetails {
  api_key: string;
  custom_config: any;
  provider_type: EmbeddingProvider;
}

export function EmbeddingModelSelection({
  selectedProvider,
  currentEmbeddingModel,
  updateSelectedProvider,
  modelTab,
  setModelTab,
}: {
  modelTab: "open" | "cloud" | null;
  setModelTab: Dispatch<SetStateAction<"open" | "cloud" | null>>;
  currentEmbeddingModel: CloudEmbeddingModel | HostedEmbeddingModel;
  selectedProvider: CloudEmbeddingModel | HostedEmbeddingModel;
  updateSelectedProvider: (
    model: CloudEmbeddingModel | HostedEmbeddingModel
  ) => void;
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

  // Enabled / unenabled providers
  const [newEnabledProviders, setNewEnabledProviders] = useState<string[]>([]);
  const [newUnenabledProviders, setNewUnenabledProviders] = useState<string[]>(
    []
  );

  const [showDeleteCredentialsModal, setShowDeleteCredentialsModal] =
    useState<boolean>(false);
  const [showAddConnectorPopup, setShowAddConnectorPopup] =
    useState<boolean>(false);

  const { data: embeddingProviderDetails } = useSWR<EmbeddingDetails[]>(
    EMBEDDING_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher
  );

  const { data: connectors } = useSWR<Connector<any>[]>(
    "/api/manage/connector",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const onConfirmSelection = async (model: EmbeddingModelDescriptor) => {
    const response = await fetch(
      "/api/search-settings/set-new-embedding-model",
      {
        method: "POST",
        body: JSON.stringify(model),
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
    if (response.ok) {
      setShowTentativeModel(null);
      mutate("/api/search-settings/get-secondary-embedding-model");
      if (!connectors || !connectors.length) {
        setShowAddConnectorPopup(true);
      }
    } else {
      alert(`Failed to update embedding model - ${await response.text()}`);
    }
  };

  const onSelectOpenSource = async (model: HostedEmbeddingModel) => {
    if (selectedProvider?.model_name === INVALID_OLD_MODEL) {
      await onConfirmSelection(model);
    } else {
      setShowTentativeOpenProvider(model);
    }
  };

  const clientsideAddProvider = (provider: CloudEmbeddingProvider) => {
    const providerType = provider.provider_type;
    setNewEnabledProviders((newEnabledProviders) => [
      ...newEnabledProviders,
      providerType,
    ]);
    setNewUnenabledProviders((newUnenabledProviders) =>
      newUnenabledProviders.filter(
        (givenProviderType) => givenProviderType != providerType
      )
    );
  };

  const clientsideRemoveProvider = (provider: CloudEmbeddingProvider) => {
    const providerType = provider.provider_type;
    setNewEnabledProviders((newEnabledProviders) =>
      newEnabledProviders.filter(
        (givenProviderType) => givenProviderType != providerType
      )
    );
    setNewUnenabledProviders((newUnenabledProviders) => [
      ...newUnenabledProviders,
      providerType,
    ]);
  };

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
          selectedProvider={showTentativeProvider}
          onConfirm={() => {
            setShowTentativeProvider(showUnconfiguredProvider);
            clientsideAddProvider(showTentativeProvider);
            if (showModelInQueue) {
              setShowTentativeModel(showModelInQueue);
            }
          }}
          onCancel={() => {
            setShowModelInQueue(null);
            setShowTentativeProvider(null);
          }}
        />
      )}
      {changeCredentialsProvider && (
        <ChangeCredentialsModal
          useFileUpload={changeCredentialsProvider.provider_type == "Google"}
          onDeleted={() => {
            clientsideRemoveProvider(changeCredentialsProvider);
            setChangeCredentialsProvider(null);
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
          }}
          onCancel={() => setShowDeleteCredentialsModal(false)}
        />
      )}

      <p className=" t mb-4">
        Select from cloud, self-hosted models, or continue with your current
        embedding model.
      </p>
      <div className="text-sm mr-auto mb-6 divide-x-2 flex">
        <button
          onClick={() => setModelTab(null)}
          className={`mr-4 p-2 font-bold  ${
            !modelTab
              ? "rounded bg-background-900 text-text-100 underline"
              : " hover:underline bg-background-100"
          }`}
        >
          Current
        </button>
        <div className="px-2 ">
          <button
            onClick={() => setModelTab("cloud")}
            className={`mx-2 p-2 font-bold  ${
              modelTab == "cloud"
                ? "rounded bg-background-900 text-text-100 underline"
                : " hover:underline bg-background-100"
            }`}
          >
            Cloud-based
          </button>
        </div>
        <div className="px-2 ">
          <button
            onClick={() => setModelTab("open")}
            className={` mx-2 p-2 font-bold  ${
              modelTab == "open"
                ? "rounded bg-background-900 text-text-100 underline"
                : "hover:underline bg-background-100"
            }`}
          >
            Self-hosted
          </button>
        </div>
      </div>

      {modelTab == "open" && (
        <OpenEmbeddingPage
          selectedProvider={selectedProvider}
          onSelectOpenSource={onSelectOpenSource}
        />
      )}

      {modelTab == "cloud" && (
        <CloudEmbeddingPage
          setShowModelInQueue={setShowModelInQueue}
          setShowTentativeModel={setShowTentativeModel}
          currentModel={selectedProvider}
          setAlreadySelectedModel={setAlreadySelectedModel}
          embeddingProviderDetails={embeddingProviderDetails}
          newEnabledProviders={newEnabledProviders}
          newUnenabledProviders={newUnenabledProviders}
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
