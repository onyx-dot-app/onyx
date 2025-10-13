"use client";

import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import {
  CloudEmbeddingProvider,
  CloudEmbeddingModel,
  AVAILABLE_CLOUD_PROVIDERS,
  CloudEmbeddingProviderFull,
  EmbeddingModelDescriptor,
  EmbeddingProvider,
  LITELLM_CLOUD_PROVIDER,
  AZURE_CLOUD_PROVIDER,
  getFormattedProviderName,
} from "../../../../components/embedding/interfaces";
import { EmbeddingDetails } from "../EmbeddingModelSelectionForm";
import { FiExternalLink, FiInfo, FiTrash } from "react-icons/fi";
import { HoverPopup } from "@/components/HoverPopup";
import { Dispatch, SetStateAction, useEffect, useState } from "react";
import { CustomEmbeddingModelForm } from "@/components/embedding/CustomEmbeddingModelForm";
import { deleteSearchSettings } from "./utils";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { AdvancedSearchConfiguration } from "../interfaces";
import CardSection from "@/components/admin/CardSection";

export default function CloudEmbeddingPage({
  currentModel,
  embeddingProviderDetails,
  embeddingModelDetails,
  setShowTentativeProvider,
  setChangeCredentialsProvider,
  setAlreadySelectedModel,
  setShowTentativeModel,
  setShowModelInQueue,
  advancedEmbeddingDetails,
}: {
  setShowModelInQueue: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  setShowTentativeModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  currentModel: EmbeddingModelDescriptor | CloudEmbeddingModel;
  setAlreadySelectedModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  embeddingModelDetails?: CloudEmbeddingModel[];
  embeddingProviderDetails?: EmbeddingDetails[];
  setShowTentativeProvider: React.Dispatch<
    React.SetStateAction<CloudEmbeddingProvider | null>
  >;
  setChangeCredentialsProvider: React.Dispatch<
    React.SetStateAction<CloudEmbeddingProvider | null>
  >;
  advancedEmbeddingDetails: AdvancedSearchConfiguration;
}) {
  function hasProviderTypeinArray(
    arr: Array<{ provider_type: string }>,
    searchName: string
  ): boolean {
    return arr.some(
      (item) => item.provider_type.toLowerCase() === searchName.toLowerCase()
    );
  }

  const providers: CloudEmbeddingProviderFull[] = AVAILABLE_CLOUD_PROVIDERS.map(
    (model) => ({
      ...model,
      configured:
        embeddingProviderDetails &&
        hasProviderTypeinArray(embeddingProviderDetails, model.provider_type),
    })
  );
  const [liteLLMProvider, setLiteLLMProvider] = useState<
    EmbeddingDetails | undefined
  >(undefined);

  const [azureProvider, setAzureProvider] = useState<
    EmbeddingDetails | undefined
  >(undefined);

  useEffect(() => {
    const liteLLMProvider = embeddingProviderDetails?.find(
      (provider) =>
        provider.provider_type === EmbeddingProvider.LITELLM.toLowerCase()
    );
    setLiteLLMProvider(liteLLMProvider);
    const azureProvider = embeddingProviderDetails?.find(
      (provider) =>
        provider.provider_type === EmbeddingProvider.AZURE.toLowerCase()
    );
    setAzureProvider(azureProvider);
  }, [embeddingProviderDetails]);

  const isAzureConfigured = azureProvider !== undefined;

  // Get details of the configured Azure provider
  const azureProviderDetails = embeddingProviderDetails?.find(
    (provider) => provider.provider_type.toLowerCase() === "azure"
  );

  return (
    <div>
      <Title className="mt-8">
        Here are some cloud-based models to choose from.
      </Title>
      <Text className="mb-4">
        These models require API keys and run in the clouds of the respective
        providers.
      </Text>

      <div className="gap-4 mt-2 pb-10 flex content-start flex-wrap">
        {providers.map((provider) => (
          <div key={provider.provider_type} className="mt-4 w-full">
            <div className="flex items-center mb-2">
              {provider.icon({ size: 40 })}
              <h2 className="ml-2  mt-2 text-xl font-bold">
                {getFormattedProviderName(provider.provider_type)}{" "}
                {provider.provider_type == EmbeddingProvider.COHERE &&
                  "(recommended)"}
              </h2>
              <HoverPopup
                mainContent={
                  <FiInfo className="ml-2 mt-2 cursor-pointer" size={18} />
                }
                popupContent={
                  <div className="text-sm text-text-800 w-52">
                    <div className="my-auto">{provider.description}</div>
                  </div>
                }
                style="dark"
              />
            </div>

            <button
              onClick={() => {
                if (!provider.configured) {
                  setShowTentativeProvider(provider);
                } else {
                  setChangeCredentialsProvider(provider);
                }
              }}
              className="mb-2  hover:underline text-sm cursor-pointer"
            >
              {provider.configured ? "Modify API key" : "Provide API key"}
            </button>
            <div className="flex flex-wrap gap-4">
              {provider.embedding_models.map((model) => (
                <CloudModelCard
                  key={model.model_name}
                  model={model}
                  provider={provider}
                  currentModel={currentModel}
                  setAlreadySelectedModel={setAlreadySelectedModel}
                  setShowTentativeModel={setShowTentativeModel}
                  setShowModelInQueue={setShowModelInQueue}
                  setShowTentativeProvider={setShowTentativeProvider}
                />
              ))}
            </div>
          </div>
        ))}

        <Text className="mt-6">
          Alternatively, you can use a self-hosted model using the LiteLLM
          proxy. This allows you to leverage various LLM providers through a
          unified interface that you control.{" "}
          <a
            href="https://docs.litellm.ai/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:underline"
          >
            Learn more about LiteLLM
          </a>
        </Text>

        <div key={LITELLM_CLOUD_PROVIDER.provider_type} className="mt-4 w-full">
          <div className="flex items-center mb-2">
            {LITELLM_CLOUD_PROVIDER.icon({ size: 40 })}
            <h2 className="ml-2  mt-2 text-xl font-bold">
              {getFormattedProviderName(LITELLM_CLOUD_PROVIDER.provider_type)}{" "}
              {LITELLM_CLOUD_PROVIDER.provider_type ==
                EmbeddingProvider.COHERE && "(recommended)"}
            </h2>
            <HoverPopup
              mainContent={
                <FiInfo className="ml-2 mt-2 cursor-pointer" size={18} />
              }
              popupContent={
                <div className="text-sm text-text-800 w-52">
                  <div className="my-auto">
                    {LITELLM_CLOUD_PROVIDER.description}
                  </div>
                </div>
              }
              style="dark"
            />
          </div>
          <div className="w-full flex flex-col items-start">
            {!liteLLMProvider ? (
              <button
                onClick={() => setShowTentativeProvider(LITELLM_CLOUD_PROVIDER)}
                className="mb-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm cursor-pointer"
              >
                Set API Configuration
              </button>
            ) : (
              <button
                onClick={() =>
                  setChangeCredentialsProvider(LITELLM_CLOUD_PROVIDER)
                }
                className="mb-2 hover:underline text-sm cursor-pointer"
              >
                Modify API Configuration
              </button>
            )}

            {!liteLLMProvider && (
              <CardSection className="mt-2 w-full max-w-4xl bg-background-50 border border-background-200">
                <div className="p-4">
                  <Text className="text-lg font-semibold mb-2">
                    API URL Required
                  </Text>
                  <Text className="text-sm text-text-600 mb-4">
                    Before you can add models, you need to provide an API URL
                    for your LiteLLM proxy. Click the &quot;Provide API
                    URL&quot; button above to set up your LiteLLM configuration.
                  </Text>
                  <div className="flex items-center">
                    <FiInfo className="text-blue-500 mr-2" size={18} />
                    <Text className="text-sm text-blue-500">
                      Once configured, you&apos;ll be able to add and manage
                      your LiteLLM models here.
                    </Text>
                  </div>
                </div>
              </CardSection>
            )}
            {liteLLMProvider && (
              <>
                <div className="flex mb-4 flex-wrap gap-4">
                  {embeddingModelDetails
                    ?.filter(
                      (model) =>
                        model.provider_type ===
                        EmbeddingProvider.LITELLM.toLowerCase()
                    )
                    .map((model) => (
                      <CloudModelCard
                        key={model.model_name}
                        model={model}
                        provider={LITELLM_CLOUD_PROVIDER}
                        currentModel={currentModel}
                        setAlreadySelectedModel={setAlreadySelectedModel}
                        setShowTentativeModel={setShowTentativeModel}
                        setShowModelInQueue={setShowModelInQueue}
                        setShowTentativeProvider={setShowTentativeProvider}
                      />
                    ))}
                </div>

                <CardSection
                  className={`mt-2 w-full max-w-4xl ${
                    currentModel.provider_type === EmbeddingProvider.LITELLM
                      ? "border-2 border-blue-500"
                      : ""
                  }`}
                >
                  <CustomEmbeddingModelForm
                    embeddingType={EmbeddingProvider.LITELLM}
                    provider={liteLLMProvider}
                    currentValues={
                      currentModel.provider_type === EmbeddingProvider.LITELLM
                        ? (currentModel as CloudEmbeddingModel)
                        : null
                    }
                    setShowTentativeModel={setShowTentativeModel}
                  />
                </CardSection>
              </>
            )}
          </div>
        </div>

        <Text className="mt-6">
          You can also use Azure OpenAI models for embeddings. Azure requires
          separate configuration for each model.
        </Text>

        <div key={AZURE_CLOUD_PROVIDER.provider_type} className="mt-4 w-full">
          <div className="flex items-center mb-2">
            {AZURE_CLOUD_PROVIDER.icon({ size: 40 })}
            <h2 className="ml-2  mt-2 text-xl font-bold">
              {getFormattedProviderName(AZURE_CLOUD_PROVIDER.provider_type)}{" "}
            </h2>
            <HoverPopup
              mainContent={
                <FiInfo className="ml-2 mt-2 cursor-pointer" size={18} />
              }
              popupContent={
                <div className="text-sm text-text-800 w-52">
                  <div className="my-auto">
                    {AZURE_CLOUD_PROVIDER.description}
                  </div>
                </div>
              }
              style="dark"
            />
          </div>
        </div>

        <div className="w-full flex flex-col items-start">
          {!isAzureConfigured ? (
            <>
              <button
                onClick={() => setShowTentativeProvider(AZURE_CLOUD_PROVIDER)}
                className="mb-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm cursor-pointer"
              >
                Configure Azure OpenAI
              </button>
              <div className="mt-2 w-full max-w-4xl">
                <CardSection className="p-4 border border-background-200 rounded-lg shadow-sm">
                  <Text className="text-base font-medium mb-2">
                    Configure Azure OpenAI for Embeddings
                  </Text>
                  <Text className="text-sm text-text-600 mb-3">
                    Click &quot;Configure Azure OpenAI&quot; to set up Azure
                    OpenAI for embeddings.
                  </Text>
                  <div className="flex items-center text-sm text-text-700">
                    <FiInfo className="text-neutral-400 mr-2" size={16} />
                    <Text>
                      You&apos;ll need: API version, base URL, API key, model
                      name, and deployment name.
                    </Text>
                  </div>
                </CardSection>
              </div>
            </>
          ) : (
            <>
              <div className="mb-6 w-full">
                <Text className="text-lg font-semibold mb-3">
                  Current Azure Configuration
                </Text>

                {azureProviderDetails ? (
                  <CardSection className="bg-white shadow-sm border border-background-200 rounded-lg">
                    <div className="p-4 space-y-3">
                      <div className="flex justify-between">
                        <span className="font-medium">API Version:</span>
                        <span>{azureProviderDetails.api_version}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="font-medium">Base URL:</span>
                        <span>{azureProviderDetails.api_url}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="font-medium">Deployment Name:</span>
                        <span>{azureProviderDetails.deployment_name}</span>
                      </div>
                    </div>
                    <button
                      onClick={() =>
                        setChangeCredentialsProvider(AZURE_CLOUD_PROVIDER)
                      }
                      className="mt-2 px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 text-sm"
                    >
                      Delete Current Azure Provider
                    </button>
                  </CardSection>
                ) : (
                  <CardSection className="bg-background-50 border border-background-200 rounded-lg">
                    <div className="p-4 text-text-500 text-center">
                      No Azure provider has been configured yet.
                    </div>
                  </CardSection>
                )}
              </div>

              <CardSection
                className={`mt-2 w-full max-w-4xl ${
                  currentModel.provider_type === EmbeddingProvider.AZURE
                    ? "border-2 border-blue-500"
                    : ""
                }`}
              >
                {azureProvider && (
                  <CustomEmbeddingModelForm
                    embeddingType={EmbeddingProvider.AZURE}
                    provider={azureProvider}
                    currentValues={
                      currentModel.provider_type === EmbeddingProvider.AZURE
                        ? (currentModel as CloudEmbeddingModel)
                        : null
                    }
                    setShowTentativeModel={setShowTentativeModel}
                  />
                )}
              </CardSection>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function CloudModelCard({
  model,
  provider,
  currentModel,
  setAlreadySelectedModel,
  setShowTentativeModel,
  setShowModelInQueue,
  setShowTentativeProvider,
}: {
  model: CloudEmbeddingModel;
  provider: CloudEmbeddingProviderFull;
  currentModel: EmbeddingModelDescriptor | CloudEmbeddingModel;
  setAlreadySelectedModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  setShowTentativeModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  setShowModelInQueue: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  setShowTentativeProvider: React.Dispatch<
    React.SetStateAction<CloudEmbeddingProvider | null>
  >;
}) {
  const { popup, setPopup } = usePopup();
  const [showDeleteModel, setShowDeleteModel] = useState(false);
  const enabled =
    model.model_name === currentModel.model_name &&
    model.provider_type?.toLowerCase() ==
      currentModel.provider_type?.toLowerCase();

  const deleteModel = async () => {
    if (!model.id) {
      setPopup({ message: "Model cannot be deleted", type: "error" });
      return;
    }

    const response = await deleteSearchSettings(model.id);

    if (response.ok) {
      setPopup({ message: "Model deleted successfully", type: "success" });
      setShowDeleteModel(false);
    } else {
      setPopup({
        message:
          "Failed to delete model. Ensure you are not attempting to delete a curently active model.",
        type: "error",
      });
    }
  };

  return (
    <div
      className={`p-4 w-96 border rounded-lg transition-all duration-200 ${
        enabled
          ? "border-blue-500 bg-blue-50 dark:bg-blue-950 shadow-md"
          : "border-background-300 hover:border-blue-300 hover:shadow-sm"
      } ${!provider.configured && "opacity-80 hover:opacity-100"}`}
    >
      {popup}
      {showDeleteModel && (
        <ConfirmEntityModal
          entityName={model.model_name}
          entityType="embedding model configuration"
          onSubmit={() => deleteModel()}
          onClose={() => setShowDeleteModel(false)}
        />
      )}

      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold dark:text-neutral-100 text-lg">
          {model.model_name}
        </h3>
        <div className="flex gap-x-2">
          {model.provider_type == EmbeddingProvider.LITELLM.toLowerCase() && (
            <button
              onClickCapture={() => setShowDeleteModel(true)}
              onClick={(e) => e.stopPropagation()}
              className="text-blue-500 hover:text-blue-700 transition-colors duration-200"
            >
              <FiTrash size={18} />
            </button>
          )}
          <a
            href={provider.website}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-blue-500 hover:text-blue-700 transition-colors duration-200"
          >
            <FiExternalLink size={18} />
          </a>
        </div>
      </div>
      <p className="text-sm text-text-600 dark:text-neutral-400 mb-2">
        {model.description}
      </p>
      {model?.provider_type?.toLowerCase() !=
        EmbeddingProvider.LITELLM.toLowerCase() && (
        <div className="text-xs text-text-500 mb-2">
          ${model.pricePerMillion}/M tokens
        </div>
      )}
      <div className="mt-3">
        <button
          className={`w-full p-2 rounded-lg text-sm ${
            enabled
              ? "bg-background-125 border border-border cursor-not-allowed"
              : "bg-background border border-border hover:bg-accent-background-hovered cursor-pointer"
          }`}
          onClick={() => {
            if (enabled) {
              setAlreadySelectedModel(model);
            } else if (
              provider.configured ||
              provider.provider_type === EmbeddingProvider.LITELLM
            ) {
              setShowTentativeModel(model);
            } else {
              setShowModelInQueue(model);
              setShowTentativeProvider(provider);
            }
          }}
          disabled={enabled}
        >
          {enabled ? "Selected Model" : "Select Model"}
        </button>
      </div>
    </div>
  );
}
