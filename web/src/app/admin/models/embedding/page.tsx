"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Button, Card, Text, Title } from "@tremor/react";
import { FiPackage } from "react-icons/fi";
import useSWR, { mutate } from "swr";
import { ModelOption, ModelSelector } from "./ModelSelector";
import { useState } from "react";
import { ModelSelectionConfirmaionModal } from "./ModelSelectionConfirmation";
import { ReindexingProgressTable } from "./ReindexingProgressTable";
import { Modal } from "@/components/Modal";
import {
  AVAILABLE_MODELS,
  EmbeddingModelDescriptor,
  INVALID_OLD_MODEL,
  fillOutEmeddingModelDescriptor,
} from "./embeddingModels";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Connector, ConnectorIndexingStatus } from "@/lib/types";
import Link from "next/link";
import { CustomModelForm } from "./CustomModelForm";

function Main() {
  const [tentativeNewEmbeddingModel, setTentativeNewEmbeddingModel] =
    useState<EmbeddingModelDescriptor | null>(null);
  const [isCancelling, setIsCancelling] = useState<boolean>(false);
  const [showAddConnectorPopup, setShowAddConnectorPopup] =
    useState<boolean>(false);

  const {
    data: currentEmeddingModel,
    isLoading: isLoadingCurrentModel,
    error: currentEmeddingModelError,
  } = useSWR<EmbeddingModelDescriptor>(
    "/api/secondary-index/get-current-embedding-model",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );
  const {
    data: futureEmbeddingModel,
    isLoading: isLoadingFutureModel,
    error: futureEmeddingModelError,
  } = useSWR<EmbeddingModelDescriptor | null>(
    "/api/secondary-index/get-secondary-embedding-model",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );
  const {
    data: ongoingReIndexingStatus,
    isLoading: isLoadingOngoingReIndexingStatus,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status?secondary_index=true",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );
  const { data: connectors } = useSWR<Connector<any>[]>(
    "/api/manage/connector",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const onSelect = async (model: EmbeddingModelDescriptor) => {
    if (currentEmeddingModel?.model_name === INVALID_OLD_MODEL) {
      await onConfirm(model);
    } else {
      setTentativeNewEmbeddingModel(model);
    }
  };

  const onConfirm = async (model: EmbeddingModelDescriptor) => {
    const response = await fetch(
      "/api/secondary-index/set-new-embedding-model",
      {
        method: "POST",
        body: JSON.stringify(model),
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
    if (response.ok) {
      setTentativeNewEmbeddingModel(null);
      mutate("/api/secondary-index/get-secondary-embedding-model");
      if (!connectors || !connectors.length) {
        setShowAddConnectorPopup(true);
      }
    } else {
      alert(`Failed to update embedding model - ${await response.text()}`);
    }
  };

  const onCancel = async () => {
    const response = await fetch("/api/secondary-index/cancel-new-embedding", {
      method: "POST",
    });
    if (response.ok) {
      setTentativeNewEmbeddingModel(null);
      mutate("/api/secondary-index/get-secondary-embedding-model");
    } else {
      alert(
        `Failed to cancel embedding model update - ${await response.text()}`
      );
    }

    setIsCancelling(false);
  };

  if (isLoadingCurrentModel || isLoadingFutureModel) {
    return <ThreeDotsLoader />;
  }

  if (
    currentEmeddingModelError ||
    !currentEmeddingModel ||
    futureEmeddingModelError
  ) {
    return <ErrorCallout errorTitle="Failed to fetch embedding model status" />;
  }

  const currentModelName = currentEmeddingModel.model_name;
  const currentModel =
    AVAILABLE_MODELS.find((model) => model.model_name === currentModelName) ||
    fillOutEmeddingModelDescriptor(currentEmeddingModel);

  const newModelSelection = futureEmbeddingModel
    ? AVAILABLE_MODELS.find(
        (model) => model.model_name === futureEmbeddingModel.model_name
      ) || fillOutEmeddingModelDescriptor(futureEmbeddingModel)
    : null;

  return (
    <div>
      {tentativeNewEmbeddingModel && (
        <ModelSelectionConfirmaionModal
          selectedModel={tentativeNewEmbeddingModel}
          isCustom={
            AVAILABLE_MODELS.find(
              (model) =>
                model.model_name === tentativeNewEmbeddingModel.model_name
            ) === undefined
          }
          onConfirm={() => onConfirm(tentativeNewEmbeddingModel)}
          onCancel={() => setTentativeNewEmbeddingModel(null)}
        />
      )}

      {showAddConnectorPopup && (
        <Modal>
          <div>
            <div>
              <b className="text-base">Embeding model successfully selected</b>{" "}
              🙌
              <br />
              <br />
              To complete the initial setup, let&apos;s add a connector!
              <br />
              <br />
              Connectors are the way that Danswer gets data from your
              organization&apos;s various data sources. Once setup, we&apos;ll
              automatically sync data from your apps and docs into Danswer, so
              you can search all through all of them in one place.
            </div>
            <div className="flex">
              <Link className="mx-auto mt-2 w-fit" href="/admin/add-connector">
                <Button className="mt-3 mx-auto" size="xs">
                  Add Connector
                </Button>
              </Link>
            </div>
          </div>
        </Modal>
      )}

      {isCancelling && (
        <Modal
          onOutsideClick={() => setIsCancelling(false)}
          title="Cancel Embedding Model Switch"
        >
          <div>
            <div>
              Are you sure you want to cancel?
              <br />
              <br />
              Cancelling will revert to the previous model and all progress will
              be lost.
            </div>
            <div className="flex">
              <Button onClick={onCancel} className="mt-3 mx-auto" color="green">
                Confirm
              </Button>
            </div>
          </div>
        </Modal>
      )}

      <Text>
        Embedding models are used to generate embeddings for your documents,
        which then power Danswer&apos;s search.
      </Text>

      {currentModel ? (
        <>
          <Title className="mt-8 mb-2">Current Embedding Model</Title>

          <Text>
            <ModelOption model={currentModel} />
          </Text>
        </>
      ) : (
        newModelSelection &&
        (!connectors || !connectors.length) && (
          <>
            <Title className="mt-8 mb-2">Current Embedding Model</Title>

            <Text>
              <ModelOption model={newModelSelection} />
            </Text>
          </>
        )
      )}

      {!showAddConnectorPopup &&
        (!newModelSelection ? (
          <div>
            {currentModel ? (
              <>
                <Title className="mt-8">Switch your Embedding Model</Title>

                <Text className="mb-4">
                  If the current model is not working for you, you can update
                  your model choice below. Note that this will require a
                  complete re-indexing of all your documents across every
                  connected source. We will take care of this in the background,
                  but depending on the size of your corpus, this could take
                  hours, day, or even weeks. You can monitor the progress of the
                  re-indexing on this page.
                </Text>
              </>
            ) : (
              <>
                <Title className="mt-8 mb-4">Choose your Embedding Model</Title>
              </>
            )}

            <Text className="mb-4">
              Below are a curated selection of quality models that we recommend
              you choose from.
            </Text>

            <ModelSelector
              modelOptions={AVAILABLE_MODELS.filter(
                (modelOption) => modelOption.model_name !== currentModelName
              )}
              setSelectedModel={onSelect}
            />

            <Text className="mt-6">
              Alternatively, (if you know what you&apos;re doing) you can
              specify a{" "}
              <a
                target="_blank"
                href="https://www.sbert.net/"
                className="text-link"
              >
                SentenceTransformers
              </a>
              -compatible model of your choice below. The rough list of
              supported models can be found{" "}
              <a
                target="_blank"
                href="https://huggingface.co/models?library=sentence-transformers&sort=trending"
                className="text-link"
              >
                here
              </a>
              .
              <br />
              <b>NOTE:</b> not all models listed will work with Danswer, since
              some have unique interfaces or special requirements. If in doubt,
              reach out to the Danswer team.
            </Text>

            <div className="w-full flex">
              <Card className="mt-4 2xl:w-4/6 mx-auto">
                <CustomModelForm onSubmit={onSelect} />
              </Card>
            </div>
          </div>
        ) : (
          connectors &&
          connectors.length > 0 && (
            <div>
              <Title className="mt-8">Current Upgrade Status</Title>
              <div className="mt-4">
                <div className="italic text-sm mb-2">
                  Currently in the process of switching to:
                </div>
                <ModelOption model={newModelSelection} />

                <Button
                  color="red"
                  size="xs"
                  className="mt-4"
                  onClick={() => setIsCancelling(true)}
                >
                  Cancel
                </Button>

                <Text className="my-4">
                  The table below shows the re-indexing progress of all existing
                  connectors. Once all connectors have been re-indexed
                  successfully, the new model will be used for all search
                  queries. Until then, we will use the old model so that no
                  downtime is necessary during this transition.
                </Text>

                {isLoadingOngoingReIndexingStatus ? (
                  <ThreeDotsLoader />
                ) : ongoingReIndexingStatus ? (
                  <ReindexingProgressTable
                    reindexingProgress={ongoingReIndexingStatus}
                  />
                ) : (
                  <ErrorCallout errorTitle="Failed to fetch re-indexing progress" />
                )}
              </div>
            </div>
          )
        ))}
    </div>
  );
}

function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Embedding"
        icon={<FiPackage size={32} className="my-auto" />}
      />

      <Main />
    </div>
  );
}

export default Page;
