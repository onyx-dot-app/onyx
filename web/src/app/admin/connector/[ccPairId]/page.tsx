"use client";

import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { SourceIcon } from "@/components/SourceIcon";
import { CCPairStatus } from "@/components/Status";
import { usePopup } from "@/components/admin/connectors/Popup";
import CredentialSection from "@/components/credentials/CredentialSection";
import {
  updateConnectorCredentialPairName,
  updateConnectorCredentialPairProperty,
} from "@/lib/connector";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ValidSources } from "@/lib/types";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, use } from "react";
import useSWR, { mutate } from "swr";
import { AdvancedConfigDisplay, ConfigDisplay } from "./ConfigDisplay";
import { DeletionButton } from "./DeletionButton";
import DeletionErrorStatus from "./DeletionErrorStatus";
import { IndexingAttemptsTable } from "./IndexingAttemptsTable";
import { ModifyStatusButtonCluster } from "./ModifyStatusButtonCluster";
import { ReIndexButton } from "./ReIndexButton";
import { buildCCPairInfoUrl, triggerIndexing } from "./lib";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  CCPairFullInfo,
  ConnectorCredentialPairStatus,
  IndexAttemptError,
  PaginatedIndexAttemptErrors,
} from "./types";
import { EditableStringFieldDisplay } from "@/components/EditableStringFieldDisplay";
import { Button } from "@/components/ui/button";
import EditPropertyModal from "@/components/modals/EditPropertyModal";

import * as Yup from "yup";
import { AlertCircle } from "lucide-react";
import IndexAttemptErrorsModal from "./IndexAttemptErrorsModal";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { IndexAttemptSnapshot } from "@/lib/types";
import { Spinner } from "@/components/Spinner";

// synchronize these validations with the SQLAlchemy connector class until we have a
// centralized schema for both frontend and backend
const RefreshFrequencySchema = Yup.object().shape({
  propertyValue: Yup.number()
    .typeError("Property value must be a valid number")
    .integer("Property value must be an integer")
    .min(60, "Property value must be greater than or equal to 60")
    .required("Property value is required"),
});

const PruneFrequencySchema = Yup.object().shape({
  propertyValue: Yup.number()
    .typeError("Property value must be a valid number")
    .integer("Property value must be an integer")
    .min(86400, "Property value must be greater than or equal to 86400")
    .required("Property value is required"),
});

const ITEMS_PER_PAGE = 8;
const PAGES_PER_BATCH = 8;

function Main({ ccPairId }: { ccPairId: number }) {
  const router = useRouter();
  const {
    data: ccPair,
    isLoading: isLoadingCCPair,
    error: ccPairError,
  } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const {
    currentPageData: indexAttempts,
    isLoading: isLoadingIndexAttempts,
    currentPage,
    totalPages,
    goToPage,
  } = usePaginatedFetch<IndexAttemptSnapshot>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: `${buildCCPairInfoUrl(ccPairId)}/index-attempts`,
  });

  const {
    currentPageData: indexAttemptErrorsPage,
    currentPage: errorsCurrentPage,
    totalPages: errorsTotalPages,
    goToPage: goToErrorsPage,
  } = usePaginatedFetch<IndexAttemptError>({
    itemsPerPage: 10,
    pagesPerBatch: 1,
    endpoint: `/api/manage/admin/cc-pair/${ccPairId}/errors`,
  });

  const indexAttemptErrors = indexAttemptErrorsPage
    ? {
        items: indexAttemptErrorsPage,
        total_items:
          errorsCurrentPage === errorsTotalPages &&
          indexAttemptErrorsPage.length === 0
            ? 0
            : errorsTotalPages * 10,
      }
    : null;

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [editingRefreshFrequency, setEditingRefreshFrequency] = useState(false);
  const [editingPruningFrequency, setEditingPruningFrequency] = useState(false);
  const [showIndexAttemptErrors, setShowIndexAttemptErrors] = useState(false);
  const [showIsResolvingKickoffLoader, setShowIsResolvingKickoffLoader] =
    useState(false);
  const { popup, setPopup } = usePopup();

  const latestIndexAttempt = indexAttempts?.[0];
  const isResolvingErrors =
    (latestIndexAttempt?.status === "in_progress" ||
      latestIndexAttempt?.status === "not_started") &&
    latestIndexAttempt?.from_beginning &&
    // if there are errors in the latest index attempt, we don't want to show the loader
    !indexAttemptErrors?.items?.some(
      (error) => error.index_attempt_id === latestIndexAttempt?.id
    );

  const finishConnectorDeletion = useCallback(() => {
    router.push("/admin/indexing/status?message=connector-deleted");
  }, [router]);

  useEffect(() => {
    if (isLoadingCCPair) {
      return;
    }
    if (ccPair && !ccPairError) {
      setHasLoadedOnce(true);
    }

    if (
      (hasLoadedOnce && (ccPairError || !ccPair)) ||
      (ccPair?.status === ConnectorCredentialPairStatus.DELETING &&
        !ccPair.connector)
    ) {
      finishConnectorDeletion();
    }
  }, [
    isLoadingCCPair,
    ccPair,
    ccPairError,
    hasLoadedOnce,
    finishConnectorDeletion,
  ]);

  const handleUpdateName = async (newName: string) => {
    try {
      const response = await updateConnectorCredentialPairName(
        ccPair?.id!,
        newName
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      mutate(buildCCPairInfoUrl(ccPairId));
      setPopup({
        message: "Connector name updated successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: `Failed to update connector name`,
        type: "error",
      });
    }
  };

  const handleRefreshEdit = async () => {
    setEditingRefreshFrequency(true);
  };

  const handlePruningEdit = async () => {
    setEditingPruningFrequency(true);
  };

  const handleRefreshSubmit = async (
    propertyName: string,
    propertyValue: string
  ) => {
    const parsedRefreshFreq = parseInt(propertyValue, 10);

    if (isNaN(parsedRefreshFreq)) {
      setPopup({
        message: "Invalid refresh frequency: must be an integer",
        type: "error",
      });
      return;
    }

    try {
      const response = await updateConnectorCredentialPairProperty(
        ccPairId,
        propertyName,
        String(parsedRefreshFreq)
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      mutate(buildCCPairInfoUrl(ccPairId));
      setPopup({
        message: "Connector refresh frequency updated successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: "Failed to update connector refresh frequency",
        type: "error",
      });
    }
  };

  const handlePruningSubmit = async (
    propertyName: string,
    propertyValue: string
  ) => {
    const parsedFreq = parseInt(propertyValue, 10);

    if (isNaN(parsedFreq)) {
      setPopup({
        message: "Invalid pruning frequency: must be an integer",
        type: "error",
      });
      return;
    }

    try {
      const response = await updateConnectorCredentialPairProperty(
        ccPairId,
        propertyName,
        String(parsedFreq)
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      mutate(buildCCPairInfoUrl(ccPairId));
      setPopup({
        message: "Connector pruning frequency updated successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: "Failed to update connector pruning frequency",
        type: "error",
      });
    }
  };

  if (isLoadingCCPair || isLoadingIndexAttempts) {
    return <ThreeDotsLoader />;
  }

  if (!ccPair || (!hasLoadedOnce && ccPairError)) {
    return (
      <ErrorCallout
        errorTitle={`Failed to fetch info on Connector with ID ${ccPairId}`}
        errorMsg={
          ccPairError?.info?.detail ||
          ccPairError?.toString() ||
          "Unknown error"
        }
      />
    );
  }

  const isDeleting = ccPair.status === ConnectorCredentialPairStatus.DELETING;

  const refresh = () => {
    mutate(buildCCPairInfoUrl(ccPairId));
  };

  const {
    prune_freq: pruneFreq,
    refresh_freq: refreshFreq,
    indexing_start: indexingStart,
  } = ccPair.connector;

  return (
    <>
      {popup}
      {showIsResolvingKickoffLoader && !isResolvingErrors && <Spinner />}

      {editingRefreshFrequency && (
        <EditPropertyModal
          propertyTitle="Refresh Frequency"
          propertyDetails="How often the connector should refresh (in seconds)"
          propertyName="refresh_frequency"
          propertyValue={String(refreshFreq)}
          validationSchema={RefreshFrequencySchema}
          onSubmit={handleRefreshSubmit}
          onClose={() => setEditingRefreshFrequency(false)}
        />
      )}

      {editingPruningFrequency && (
        <EditPropertyModal
          propertyTitle="Pruning Frequency"
          propertyDetails="How often the connector should be pruned (in seconds)"
          propertyName="pruning_frequency"
          propertyValue={String(pruneFreq)}
          validationSchema={PruneFrequencySchema}
          onSubmit={handlePruningSubmit}
          onClose={() => setEditingPruningFrequency(false)}
        />
      )}

      {showIndexAttemptErrors && indexAttemptErrors && (
        <IndexAttemptErrorsModal
          errors={indexAttemptErrors}
          onClose={() => setShowIndexAttemptErrors(false)}
          onResolveAll={async () => {
            setShowIndexAttemptErrors(false);
            setShowIsResolvingKickoffLoader(true);
            await triggerIndexing(
              true,
              ccPair.connector.id,
              ccPair.credential.id,
              ccPair.id,
              setPopup
            );

            // show the loader for a max of 10 seconds
            setTimeout(() => {
              setShowIsResolvingKickoffLoader(false);
            }, 10000);
          }}
          isResolvingErrors={isResolvingErrors}
          onPageChange={goToErrorsPage}
          currentPage={errorsCurrentPage}
        />
      )}

      <BackButton
        behaviorOverride={() => router.push("/admin/indexing/status")}
      />
      <div className="flex items-center justify-between h-14">
        <div className="my-auto">
          <SourceIcon iconSize={32} sourceType={ccPair.connector.source} />
        </div>

        <div className="ml-1 overflow-hidden text-ellipsis whitespace-nowrap flex-1 mr-4">
          <EditableStringFieldDisplay
            value={ccPair.name}
            isEditable={ccPair.is_editable_for_current_user}
            onUpdate={handleUpdateName}
            scale={2.1}
          />
        </div>

        {ccPair.is_editable_for_current_user && (
          <div className="ml-auto flex gap-x-2">
            <ReIndexButton
              ccPairId={ccPair.id}
              connectorId={ccPair.connector.id}
              credentialId={ccPair.credential.id}
              isDisabled={
                ccPair.indexing ||
                ccPair.status === ConnectorCredentialPairStatus.PAUSED
              }
              isIndexing={ccPair.indexing}
              isDeleting={isDeleting}
            />

            {!isDeleting && <ModifyStatusButtonCluster ccPair={ccPair} />}
          </div>
        )}
      </div>
      <CCPairStatus
        status={ccPair.last_index_attempt_status || "not_started"}
        disabled={ccPair.status === ConnectorCredentialPairStatus.PAUSED}
        isDeleting={isDeleting}
      />
      <div className="text-sm mt-1">
        Creator:{" "}
        <b className="text-emphasis">{ccPair.creator_email ?? "Unknown"}</b>
      </div>
      <div className="text-sm mt-1">
        Total Documents Indexed:{" "}
        <b className="text-emphasis">{ccPair.num_docs_indexed}</b>
      </div>
      {!ccPair.is_editable_for_current_user && (
        <div className="text-sm mt-2 text-text-500 italic">
          {ccPair.access_type === "public"
            ? "Public connectors are not editable by curators."
            : ccPair.access_type === "sync"
              ? "Sync connectors are not editable by curators unless the curator is also the owner."
              : "This connector belongs to groups where you don't have curator permissions, so it's not editable."}
        </div>
      )}

      {ccPair.deletion_failure_message &&
        ccPair.status === ConnectorCredentialPairStatus.DELETING && (
          <>
            <div className="mt-6" />
            <DeletionErrorStatus
              deletion_failure_message={ccPair.deletion_failure_message}
            />
          </>
        )}

      {credentialTemplates[ccPair.connector.source] &&
        ccPair.is_editable_for_current_user && (
          <>
            <Separator />

            <Title className="mb-2">Credentials</Title>

            <CredentialSection
              ccPair={ccPair}
              sourceType={ccPair.connector.source}
              refresh={() => refresh()}
            />
          </>
        )}
      <Separator />
      <ConfigDisplay
        connectorSpecificConfig={ccPair.connector.connector_specific_config}
        sourceType={ccPair.connector.source}
      />

      {(pruneFreq || indexingStart || refreshFreq) && (
        <AdvancedConfigDisplay
          pruneFreq={pruneFreq}
          indexingStart={indexingStart}
          refreshFreq={refreshFreq}
          onRefreshEdit={handleRefreshEdit}
          onPruningEdit={handlePruningEdit}
        />
      )}

      <div className="mt-6">
        <div className="flex">
          <Title>Indexing Attempts</Title>
        </div>
        {indexAttemptErrors && indexAttemptErrors.total_items > 0 && (
          <Alert className="border-alert bg-yellow-50 my-2">
            <AlertCircle className="h-4 w-4 text-yellow-700" />
            <AlertTitle className="text-yellow-950 font-semibold">
              Some documents failed to index
            </AlertTitle>
            <AlertDescription className="text-yellow-900">
              {isResolvingErrors ? (
                <span>
                  <span className="text-sm text-yellow-700 animate-pulse">
                    Resolving failures
                  </span>
                </span>
              ) : (
                <>
                  We ran into some issues while processing some documents.{" "}
                  <b
                    className="text-link cursor-pointer"
                    onClick={() => setShowIndexAttemptErrors(true)}
                  >
                    View details.
                  </b>
                </>
              )}
            </AlertDescription>
          </Alert>
        )}
        {indexAttempts && (
          <IndexingAttemptsTable
            ccPair={ccPair}
            indexAttempts={indexAttempts}
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={goToPage}
          />
        )}
      </div>
      <Separator />
      <div className="flex mt-4">
        <div className="mx-auto">
          {ccPair.is_editable_for_current_user && (
            <DeletionButton ccPair={ccPair} refresh={refresh} />
          )}
        </div>
      </div>
    </>
  );
}

export default function Page(props: { params: Promise<{ ccPairId: string }> }) {
  const params = use(props.params);
  const ccPairId = parseInt(params.ccPairId);

  return (
    <div className="mx-auto container">
      <Main ccPairId={ccPairId} />
    </div>
  );
}
