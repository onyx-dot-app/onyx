import { ThreeDotsLoader } from "@/components/Loading";
import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  ConnectorIndexingStatus,
  ConnectorIndexingStatusLite,
  ConnectorIndexingStatusLiteResponse,
  FailedConnectorIndexingStatus,
  ValidStatuses,
} from "@/lib/types";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import { useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { ReindexingProgressTable } from "../../../../components/embedding/ReindexingProgressTable";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  CloudEmbeddingModel,
  HostedEmbeddingModel,
} from "../../../../components/embedding/interfaces";
import { Connector } from "@/lib/connectors/connectors";
import { FailedReIndexAttempts } from "@/components/embedding/FailedReIndexAttempts";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useConnectorIndexingStatusWithPagination } from "@/lib/hooks";

export default function UpgradingPage({
  futureEmbeddingModel,
}: {
  futureEmbeddingModel: CloudEmbeddingModel | HostedEmbeddingModel;
}) {
  const [isCancelling, setIsCancelling] = useState<boolean>(false);

  const { setPopup, popup } = usePopup();
  const { data: connectors, isLoading: isLoadingConnectors } = useSWR<
    Connector<any>[]
  >("/api/manage/connector", errorHandlingFetcher, {
    refreshInterval: 5000, // 5 seconds
  });

  const {
    data: connectorIndexingStatuses,
    isLoading: isLoadingOngoingReIndexingStatus,
  } = useConnectorIndexingStatusWithPagination(
    { secondary_index: true, get_all_connectors: true },
    5000
  ) as {
    data: ConnectorIndexingStatusLiteResponse[];
    isLoading: boolean;
  };

  const { data: failedIndexingStatus } = useSWR<
    FailedConnectorIndexingStatus[]
  >(
    "/api/manage/admin/connector/failed-indexing-status?secondary_index=true",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const onCancel = async () => {
    const response = await fetch("/api/search-settings/cancel-new-embedding", {
      method: "POST",
    });
    if (response.ok) {
      mutate("/api/search-settings/get-secondary-search-settings");
    } else {
      alert(
        `Failed to cancel embedding model update - ${await response.text()}`
      );
    }
    setIsCancelling(false);
  };
  const statusOrder: Record<ValidStatuses, number> = useMemo(
    () => ({
      invalid: 0,
      failed: 1,
      canceled: 2,
      completed_with_errors: 3,
      not_started: 4,
      in_progress: 5,
      success: 6,
    }),
    []
  );

  const ongoingReIndexingStatus = useMemo(() => {
    return connectorIndexingStatuses
      .flatMap(
        (status) => status.indexing_statuses as ConnectorIndexingStatusLite[]
      )
      .filter((status) => status.cc_pair_id !== undefined);
  }, [connectorIndexingStatuses]);

  const sortedReindexingProgress = useMemo(() => {
    return [...(ongoingReIndexingStatus || [])].sort((a, b) => {
      const statusComparison =
        statusOrder[a.last_status || "not_started"] -
        statusOrder[b.last_status || "not_started"];

      if (statusComparison !== 0) {
        return statusComparison;
      }

      return (a.cc_pair_id || 0) - (b.cc_pair_id || 0);
    });
  }, [ongoingReIndexingStatus, statusOrder]);

  if (isLoadingConnectors || isLoadingOngoingReIndexingStatus) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      {popup}
      {isCancelling && (
        <Modal
          onOutsideClick={() => setIsCancelling(false)}
          title="Cancel Embedding Model Switch"
        >
          <div>
            <div>
              Are you sure you want to cancel? Cancelling will revert to the
              previous model and all progress will be lost.
            </div>
            <div className="mt-12 gap-x-2 w-full justify-end flex">
              <Button onClick={onCancel}>Confirm</Button>
              <Button onClick={() => setIsCancelling(false)} variant="outline">
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {futureEmbeddingModel && (
        <div>
          <Title className="mt-8">Current Upgrade Status</Title>
          <div className="mt-4">
            <div className="italic text-lg mb-2">
              Currently in the process of switching to:{" "}
              {futureEmbeddingModel.model_name}
            </div>

            <Button
              variant="destructive"
              className="mt-4"
              onClick={() => setIsCancelling(true)}
            >
              Cancel
            </Button>

            {connectors && connectors.length > 0 ? (
              futureEmbeddingModel.background_reindex_enabled ? (
                <>
                  {failedIndexingStatus && failedIndexingStatus.length > 0 && (
                    <FailedReIndexAttempts
                      failedIndexingStatuses={failedIndexingStatus}
                      setPopup={setPopup}
                    />
                  )}

                  <Text className="my-4">
                    The table below shows the re-indexing progress of all
                    existing connectors. Once all connectors have been
                    re-indexed successfully, the new model will be used for all
                    search queries. Until then, we will use the old model so
                    that no downtime is necessary during this transition.
                    <br />
                    Note: User file re-indexing progress is not shown. You will
                    see this page until all user files are re-indexed!
                  </Text>

                  {sortedReindexingProgress ? (
                    <ReindexingProgressTable
                      reindexingProgress={sortedReindexingProgress}
                    />
                  ) : (
                    <ErrorCallout errorTitle="Failed to fetch re-indexing progress" />
                  )}
                </>
              ) : (
                <div className="mt-8">
                  <h3 className="text-lg font-semibold mb-2">
                    Switching Embedding Models
                  </h3>
                  <p className="mb-4 text-text-800">
                    You&apos;re currently switching embedding models, and
                    you&apos;ve selected the instant switch option. The
                    transition will complete shortly.
                  </p>
                  <p className="text-text-600">
                    The new model will be active soon.
                  </p>
                </div>
              )
            ) : (
              <div className="mt-8 p-6 bg-background-100 border border-border-strong rounded-lg max-w-2xl">
                <h3 className="text-lg font-semibold mb-2">
                  Switching Embedding Models
                </h3>
                <p className="mb-4 text-text-800">
                  You&apos;re currently switching embedding models, but there
                  are no connectors to reindex. This means the transition will
                  be quick and seamless!
                </p>
                <p className="text-text-600">
                  The new model will be active soon.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
