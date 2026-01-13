import { ThreeDotsLoader } from "@/components/Loading";
import Modal from "@/refresh-components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  ConnectorIndexingStatusLite,
  ConnectorIndexingStatusLiteResponse,
  FailedConnectorIndexingStatus,
  ValidStatuses,
} from "@/lib/types";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import Button from "@/refresh-components/buttons/Button";
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
import { SvgX } from "@opal/icons";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";

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

  const visibleReindexingStatus = useMemo(() => {
    const statuses = ongoingReIndexingStatus || [];

    if (futureEmbeddingModel.switchover_type === "active_only") {
      return statuses.filter(
        (status) =>
          status.cc_pair_status !== ConnectorCredentialPairStatus.PAUSED
      );
    }

    return statuses;
  }, [futureEmbeddingModel.switchover_type, ongoingReIndexingStatus]);

  const sortedReindexingProgress = useMemo(() => {
    return [...(visibleReindexingStatus || [])].sort((a, b) => {
      const statusComparison =
        statusOrder[a.last_status || "not_started"] -
        statusOrder[b.last_status || "not_started"];

      if (statusComparison !== 0) {
        return statusComparison;
      }

      return (a.cc_pair_id || 0) - (b.cc_pair_id || 0);
    });
  }, [visibleReindexingStatus, statusOrder]);

  const hasVisibleReindexingProgress = sortedReindexingProgress.length > 0;

  if (isLoadingConnectors || isLoadingOngoingReIndexingStatus) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      {popup}
      {isCancelling && (
        <Modal open onOpenChange={() => setIsCancelling(false)}>
          <Modal.Content small>
            <Modal.Header
              icon={SvgX}
              title="Cancel Embedding Model Switch"
              onClose={() => setIsCancelling(false)}
            />
            <Modal.Body>
              <div>
                Are you sure you want to cancel? Cancelling will revert to the
                previous model and all progress will be lost.
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={onCancel}>Confirm</Button>
              <Button onClick={() => setIsCancelling(false)} secondary>
                Cancel
              </Button>
            </Modal.Footer>
          </Modal.Content>
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
              danger
              className="mt-4"
              onClick={() => setIsCancelling(true)}
            >
              Cancel
            </Button>

            {connectors && connectors.length > 0 ? (
              futureEmbeddingModel.switchover_type === "instant" ? (
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
              ) : (
                <>
                  {failedIndexingStatus && failedIndexingStatus.length > 0 && (
                    <FailedReIndexAttempts
                      failedIndexingStatuses={failedIndexingStatus}
                      setPopup={setPopup}
                    />
                  )}

                  <Text className="my-4">
                    {futureEmbeddingModel.switchover_type === "active_only" ? (
                      <>
                        The table below shows the re-indexing progress of active
                        (non-paused) connectors. Once all active connectors have
                        been re-indexed successfully, the new model will be used
                        for all search queries. Paused connectors will continue
                        to be indexed in the background but won&apos;t block the
                        switchover. Until then, we will use the old model so
                        that no downtime is necessary during this transition.
                        <br />
                        Note: User file re-indexing progress is not shown. You
                        will see this page until all active connectors are
                        re-indexed!
                      </>
                    ) : (
                      <>
                        The table below shows the re-indexing progress of all
                        existing connectors. Once all connectors have been
                        re-indexed successfully, the new model will be used for
                        all search queries. Until then, we will use the old
                        model so that no downtime is necessary during this
                        transition.
                        <br />
                        Note: User file re-indexing progress is not shown. You
                        will see this page until all user files are re-indexed!
                      </>
                    )}
                  </Text>

                  {sortedReindexingProgress ? (
                    <>
                      {futureEmbeddingModel.switchover_type === "active_only" &&
                        !hasVisibleReindexingProgress && (
                          <Text className="text-text-700 mt-4">
                            All connectors are currently paused, so none are
                            blocking the switchover. Paused connectors will keep
                            re-indexing in the background.
                          </Text>
                        )}
                      {hasVisibleReindexingProgress && (
                        <ReindexingProgressTable
                          reindexingProgress={sortedReindexingProgress}
                        />
                      )}
                    </>
                  ) : (
                    <ErrorCallout errorTitle="Failed to fetch re-indexing progress" />
                  )}
                </>
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
