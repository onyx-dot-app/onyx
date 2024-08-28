import { ThreeDotsLoader } from "@/components/Loading";
import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ConnectorIndexingStatus } from "@/lib/types";
import { Button, Text, Title } from "@tremor/react";
import { useState } from "react";
import useSWR, { mutate } from "swr";
import { ReindexingProgressTable } from "../../../../components/embedding/ReindexingProgressTable";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  CloudEmbeddingModel,
  HostedEmbeddingModel,
} from "../../../../components/embedding/interfaces";
import { Connector } from "@/lib/connectors/connectors";

export default function UpgradingPage({
  futureEmbeddingModel,
}: {
  futureEmbeddingModel: CloudEmbeddingModel | HostedEmbeddingModel;
}) {
  const [isCancelling, setIsCancelling] = useState<boolean>(false);

  const { data: connectors } = useSWR<Connector<any>[]>(
    "/api/manage/connector",
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

  const onCancel = async () => {
    const response = await fetch("/api/search-settings/cancel-new-embedding", {
      method: "POST",
    });
    if (response.ok) {
      mutate("/api/search-settings/get-secondary-embedding-model");
    } else {
      alert(
        `Failed to cancel embedding model update - ${await response.text()}`
      );
    }
    setIsCancelling(false);
  };

  return (
    <>
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

      {futureEmbeddingModel && connectors && connectors.length > 0 && (
        <div>
          <Title className="mt-8">Current Upgrade Status</Title>
          <div className="mt-4">
            <div className="italic text-lg mb-2">
              Currently in the process of switching to:{" "}
              {futureEmbeddingModel.model_name}
            </div>

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
              connectors. Once all connectors have been re-indexed successfully,
              the new model will be used for all search queries. Until then, we
              will use the old model so that no downtime is necessary during
              this transition.
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
      )}
    </>
  );
}
