"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { ThreeDotsLoader } from "@/components/Loading";
import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  ConnectorIndexingStatus,
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

export default function UpgradingPage({
  futureEmbeddingModel,
}: {
  futureEmbeddingModel: CloudEmbeddingModel | HostedEmbeddingModel;
}) {
  const { t } = useTranslation();
  const [isCancelling, setIsCancelling] = useState<boolean>(false);

  const { setPopup, popup } = usePopup();
  const { data: connectors, isLoading: isLoadingConnectors } = useSWR<
    Connector<any>[]
  >("/api/manage/connector", errorHandlingFetcher, {
    refreshInterval: 5000, // 5 seconds
  });

  const {
    data: ongoingReIndexingStatus,
    isLoading: isLoadingOngoingReIndexingStatus,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status?secondary_index=true",
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

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
      alert(t(k.FAILED_TO_CANCEL_EMBEDDING_UPDATE));
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

  const sortedReindexingProgress = useMemo(() => {
    return [...(ongoingReIndexingStatus || [])].sort((a, b) => {
      const statusComparison =
        statusOrder[a.latest_index_attempt?.status || "not_started"] -
        statusOrder[b.latest_index_attempt?.status || "not_started"];

      if (statusComparison !== 0) {
        return statusComparison;
      }

      return (
        (a.latest_index_attempt?.id || 0) - (b.latest_index_attempt?.id || 0)
      );
    });
  }, [ongoingReIndexingStatus]);

  if (isLoadingConnectors || isLoadingOngoingReIndexingStatus) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      {popup}
      {isCancelling && (
        <Modal
          onOutsideClick={() => setIsCancelling(false)}
          title={t(k.CANCEL_EMBEDDING_MODEL_SWITCH)}
        >
          <div>
            <div>{t(k.ARE_YOU_SURE_YOU_WANT_TO_CANCE)}</div>
            <div className="mt-12 gap-x-2 w-full justify-end flex">
              <Button onClick={onCancel}>{t(k.CONFIRM)}</Button>
              <Button onClick={() => setIsCancelling(false)} variant="outline">
                {t(k.CANCEL)}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {futureEmbeddingModel && (
        <div>
          <Title className="mt-8">{t(k.CURRENT_UPGRADE_STATUS)}</Title>
          <div className="mt-4">
            <div className="italic text-lg mb-2">
              {t(k.CURRENTLY_IN_THE_PROCESS_OF_SW)}{" "}
              {futureEmbeddingModel.model_name}
            </div>

            <Button
              variant="destructive"
              className="mt-4"
              onClick={() => setIsCancelling(true)}
            >
              {t(k.CANCEL)}
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
                    {t(k.THE_TABLE_BELOW_SHOWS_THE_RE_I)}
                  </Text>

                  {sortedReindexingProgress ? (
                    <ReindexingProgressTable
                      reindexingProgress={sortedReindexingProgress}
                    />
                  ) : (
                    <ErrorCallout
                      errorTitle={t(k.FAILED_TO_GET_REINDEXING_PROGRESS)}
                    />
                  )}
                </>
              ) : (
                <div className="mt-8">
                  <h3 className="text-lg font-semibold mb-2">
                    {t(k.SWITCHING_EMBEDDING_MODELS)}
                  </h3>
                  <p className="mb-4 text-text-800">
                    {t(k.YOU_RE_CURRENTLY_SWITCHING_EMB)}
                  </p>
                  <p className="text-text-600">
                    {t(k.THE_NEW_MODEL_WILL_BE_ACTIVE_S)}
                  </p>
                </div>
              )
            ) : (
              <div className="mt-8 p-6 bg-background-100 border border-border-strong rounded-lg max-w-2xl">
                <h3 className="text-lg font-semibold mb-2">
                  {t(k.SWITCHING_EMBEDDING_MODELS)}
                </h3>
                <p className="mb-4 text-text-800">
                  {t(k.YOU_RE_CURRENTLY_SWITCHING_EMB1)}
                </p>
                <p className="text-text-600">
                  {t(k.THE_NEW_MODEL_WILL_BE_ACTIVE_S)}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
