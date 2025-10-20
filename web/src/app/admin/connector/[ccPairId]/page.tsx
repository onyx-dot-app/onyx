"use client";

import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { SourceIcon } from "@/components/SourceIcon";
import { CCPairStatus, PermissionSyncStatus } from "@/components/Status";
import { usePopup } from "@/components/admin/connectors/Popup";
import CredentialSection from "@/components/credentials/CredentialSection";
import Text from "@/refresh-components/texts/Text";
import {
  updateConnectorCredentialPairName,
  updateConnectorCredentialPairProperty,
} from "@/lib/connector";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Title from "@/components/ui/title";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, use } from "react";
import useSWR, { mutate } from "swr";
import {
  AdvancedConfigDisplay,
  buildConfigEntries,
  ConfigDisplay,
} from "./ConfigDisplay";
import DeletionErrorStatus from "./DeletionErrorStatus";
import { IndexAttemptsTable } from "./IndexAttemptsTable";

import { buildCCPairInfoUrl, triggerIndexing } from "./lib";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  CCPairFullInfo,
  ConnectorCredentialPairStatus,
  IndexAttemptError,
  statusIsNotCurrentlyActive,
} from "./types";
import { EditableStringFieldDisplay } from "@/components/EditableStringFieldDisplay";
import EditPropertyModal from "@/components/modals/EditPropertyModal";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { deleteCCPair } from "@/lib/documentDeletion";
import * as Yup from "yup";
import {
  AlertCircle,
  PlayIcon,
  PauseIcon,
  Trash2Icon,
  RefreshCwIcon,
} from "lucide-react";
import IndexAttemptErrorsModal from "./IndexAttemptErrorsModal";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { IndexAttemptSnapshot } from "@/lib/types";
import { Spinner } from "@/components/Spinner";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DropdownMenuItemWithTooltip } from "@/components/ui/dropdown-menu-with-tooltip";
import { timeAgo } from "@/lib/time";
import { useStatusChange } from "./useStatusChange";
import { useReIndexModal } from "./ReIndexModal";
import Button from "@/refresh-components/buttons/Button";
import SvgSettings from "@/icons/settings";

// synchronize these validations with the SQLAlchemy connector class until we have a
// centralized schema for both frontend and backend
const RefreshFrequencySchema = Yup.object().shape({
  propertyValue: Yup.number()
    .typeError("Property value must be a valid number")
    .integer("Property value must be an integer")
    .min(1, "Property value must be greater than or equal to 1 minute")
    .required("Property value is required"),
});

const PruneFrequencySchema = Yup.object().shape({
  propertyValue: Yup.number()
    .typeError("Property value must be a valid number")
    .min(
      0.083,
      "Property value must be greater than or equal to 0.083 hours (5 minutes)"
    )
    .required("Property value is required"),
});

const ITEMS_PER_PAGE = 8;
const PAGES_PER_BATCH = 8;

function Main({ ccPairId }: { ccPairId: number }) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

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

  const { currentPageData: indexAttemptErrorsPage } =
    usePaginatedFetch<IndexAttemptError>({
      itemsPerPage: 10,
      pagesPerBatch: 1,
      endpoint: `/api/manage/admin/cc-pair/${ccPairId}/errors`,
    });

  // Initialize hooks at top level to avoid conditional hook calls
  const { showReIndexModal, ReIndexModal } = useReIndexModal(
    ccPair?.connector?.id ?? null,
    ccPair?.credential?.id ?? null,
    ccPairId,
    setPopup
  );

  const {
    handleStatusChange,
    isUpdating: isStatusUpdating,
    ConfirmModal,
  } = useStatusChange(ccPair || null);

  const indexAttemptErrors = indexAttemptErrorsPage
    ? {
        items: indexAttemptErrorsPage,
        total_items: indexAttemptErrorsPage.length,
      }
    : null;

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [editingRefreshFrequency, setEditingRefreshFrequency] = useState(false);
  const [editingPruningFrequency, setEditingPruningFrequency] = useState(false);
  const [showIndexAttemptErrors, setShowIndexAttemptErrors] = useState(false);

  const [showIsResolvingKickoffLoader, setShowIsResolvingKickoffLoader] =
    useState(false);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

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

  const handleStatusUpdate = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    setShowIsResolvingKickoffLoader(true); // Show fullscreen spinner
    await handleStatusChange(newStatus);
    setShowIsResolvingKickoffLoader(false); // Hide fullscreen spinner
  };

  const triggerReIndex = async (fromBeginning: boolean) => {
    if (!ccPair) return;

    setShowIsResolvingKickoffLoader(true);

    try {
      const result = await triggerIndexing(
        fromBeginning,
        ccPair.connector.id,
        ccPair.credential.id,
        ccPair.id,
        setPopup
      );

      if (result.success) {
        setPopup({
          message: `${
            fromBeginning ? "Complete re-indexing" : "Indexing update"
          } started successfully`,
          type: "success",
        });
      } else {
        setPopup({
          message: result.message || "Failed to start indexing",
          type: "error",
        });
      }
    } catch (error) {
      console.error("Failed to trigger indexing:", error);
      setPopup({
        message: "An unexpected error occurred while trying to start indexing",
        type: "error",
      });
    } finally {
      setShowIsResolvingKickoffLoader(false);
    }
  };

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
    const parsedRefreshFreqMinutes = parseInt(propertyValue, 10);

    if (isNaN(parsedRefreshFreqMinutes)) {
      setPopup({
        message: "Invalid refresh frequency: must be an integer",
        type: "error",
      });
      return;
    }

    // Convert minutes to seconds
    const parsedRefreshFreqSeconds = parsedRefreshFreqMinutes * 60;

    try {
      const response = await updateConnectorCredentialPairProperty(
        ccPairId,
        propertyName,
        String(parsedRefreshFreqSeconds)
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
    const parsedFreqHours = parseFloat(propertyValue);

    if (isNaN(parsedFreqHours)) {
      setPopup({
        message: "Invalid pruning frequency: must be a valid number",
        type: "error",
      });
      return;
    }

    // Convert hours to seconds
    const parsedFreqSeconds = parsedFreqHours * 3600;

    try {
      const response = await updateConnectorCredentialPairProperty(
        ccPairId,
        propertyName,
        String(parsedFreqSeconds)
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
      {ReIndexModal}
      {ConfirmModal}

      {editingRefreshFrequency && (
        <EditPropertyModal
          propertyTitle="Refresh Frequency"
          propertyDetails="How often the connector should refresh (in minutes)"
          propertyName="refresh_frequency"
          propertyValue={String(Math.round((refreshFreq || 0) / 60))}
          validationSchema={RefreshFrequencySchema}
          onSubmit={handleRefreshSubmit}
          onClose={() => setEditingRefreshFrequency(false)}
        />
      )}

      {editingPruningFrequency && (
        <EditPropertyModal
          propertyTitle="Pruning Frequency"
          propertyDetails="How often the connector should be pruned (in hours)"
          propertyName="pruning_frequency"
          propertyValue={String(
            ((pruneFreq || 0) / 3600).toFixed(3).replace(/\.?0+$/, "")
          )}
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
            await triggerReIndex(true);
          }}
          isResolvingErrors={isResolvingErrors}
        />
      )}

      <BackButton
        behaviorOverride={() => router.push("/admin/indexing/status")}
      />
      <div
        className="flex
        items-center
        justify-between
        h-16
        pb-2
        border-b
        border-neutral-200
        dark:border-neutral-600"
      >
        <div className="my-auto">
          <SourceIcon iconSize={32} sourceType={ccPair.connector.source} />
        </div>

        <div className="ml-2 overflow-hidden text-ellipsis whitespace-nowrap flex-1 mr-4">
          <EditableStringFieldDisplay
            value={ccPair.name}
            isEditable={ccPair.is_editable_for_current_user}
            onUpdate={handleUpdateName}
            scale={2.1}
          />
        </div>

        <div className="ml-auto flex gap-x-2">
          {ccPair.is_editable_for_current_user && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  leftIcon={SvgSettings}
                  className="flex items-center gap-x-1"
                  secondary
                >
                  Manage
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItemWithTooltip
                  onClick={() => {
                    if (
                      !ccPair.indexing &&
                      ccPair.status !== ConnectorCredentialPairStatus.PAUSED &&
                      ccPair.status !== ConnectorCredentialPairStatus.INVALID
                    ) {
                      showReIndexModal();
                    }
                  }}
                  disabled={
                    ccPair.indexing ||
                    ccPair.status === ConnectorCredentialPairStatus.PAUSED ||
                    ccPair.status === ConnectorCredentialPairStatus.INVALID
                  }
                  className="flex items-center gap-x-2 cursor-pointer px-3 py-2"
                  tooltip={
                    ccPair.indexing
                      ? "Cannot re-index while indexing is already in progress"
                      : ccPair.status === ConnectorCredentialPairStatus.PAUSED
                        ? "Resume the connector before re-indexing"
                        : ccPair.status ===
                            ConnectorCredentialPairStatus.INVALID
                          ? "Fix the connector configuration before re-indexing"
                          : undefined
                  }
                >
                  <RefreshCwIcon className="h-4 w-4" />
                  <span>Re-Index</span>
                </DropdownMenuItemWithTooltip>
                {!isDeleting && (
                  <DropdownMenuItemWithTooltip
                    onClick={() =>
                      handleStatusUpdate(
                        statusIsNotCurrentlyActive(ccPair.status)
                          ? ConnectorCredentialPairStatus.ACTIVE
                          : ConnectorCredentialPairStatus.PAUSED
                      )
                    }
                    disabled={isStatusUpdating}
                    className="flex items-center gap-x-2 cursor-pointer px-3 py-2"
                    tooltip={
                      isStatusUpdating ? "Status update in progress" : undefined
                    }
                  >
                    {statusIsNotCurrentlyActive(ccPair.status) ? (
                      <PlayIcon className="h-4 w-4" />
                    ) : (
                      <PauseIcon className="h-4 w-4" />
                    )}
                    <span>
                      {statusIsNotCurrentlyActive(ccPair.status)
                        ? "Resume"
                        : "Pause"}
                    </span>
                  </DropdownMenuItemWithTooltip>
                )}
                {!isDeleting && (
                  <DropdownMenuItemWithTooltip
                    onClick={async () => {
                      try {
                        await deleteCCPair(
                          ccPair.connector.id,
                          ccPair.credential.id,
                          setPopup,
                          () => mutate(buildCCPairInfoUrl(ccPair.id))
                        );
                        refresh();
                      } catch (error) {
                        console.error("Error deleting connector:", error);
                      }
                    }}
                    disabled={!statusIsNotCurrentlyActive(ccPair.status)}
                    className="flex items-center gap-x-2 cursor-pointer px-3 py-2 text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                    tooltip={
                      !statusIsNotCurrentlyActive(ccPair.status)
                        ? "Pause the connector before deleting"
                        : undefined
                    }
                  >
                    <Trash2Icon className="h-4 w-4" />
                    <span>Delete</span>
                  </DropdownMenuItemWithTooltip>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {ccPair.deletion_failure_message &&
        ccPair.status === ConnectorCredentialPairStatus.DELETING && (
          <>
            <div className="mt-6" />
            <DeletionErrorStatus
              deletion_failure_message={ccPair.deletion_failure_message}
            />
          </>
        )}

      {ccPair.status === ConnectorCredentialPairStatus.INVALID && (
        <div className="mt-6">
          <Callout type="warning" title="Invalid Connector State">
            This connector is in an invalid state. Please update your
            credentials or create a new connector before re-indexing.
          </Callout>
        </div>
      )}

      {indexAttemptErrors && indexAttemptErrors.total_items > 0 && (
        <Alert className="border-alert bg-yellow-50 dark:bg-yellow-800 my-2 mt-6">
          <AlertCircle className="h-4 w-4 text-yellow-700 dark:text-yellow-500" />
          <AlertTitle className="text-yellow-950 dark:text-yellow-200 font-semibold">
            Some documents failed to index
          </AlertTitle>
          <AlertDescription className="text-yellow-900 dark:text-yellow-300">
            {isResolvingErrors ? (
              <span>
                <span className="text-sm text-yellow-700 dark:text-yellow-400 da animate-pulse">
                  Resolving failures
                </span>
              </span>
            ) : (
              <>
                We ran into some issues while processing some documents.{" "}
                <b
                  className="text-link cursor-pointer dark:text-blue-300"
                  onClick={() => setShowIndexAttemptErrors(true)}
                >
                  View details.
                </b>
              </>
            )}
          </AlertDescription>
        </Alert>
      )}

      <Title className="mb-2 mt-6" size="md">
        Indexing
      </Title>

      <Card className="px-8 py-12">
        <div className="flex">
          <div className="w-[200px]">
            <div className="text-sm font-medium mb-1">Status</div>
            <CCPairStatus
              ccPairStatus={ccPair.status}
              inRepeatedErrorState={ccPair.in_repeated_error_state}
              lastIndexAttemptStatus={latestIndexAttempt?.status}
            />
          </div>

          <div className="w-[200px]">
            <div className="text-sm font-medium mb-1">Documents Indexed</div>
            <div className="text-sm text-text-default flex items-center gap-x-1">
              {ccPair.num_docs_indexed.toLocaleString()}
              {ccPair.status ===
                ConnectorCredentialPairStatus.INITIAL_INDEXING &&
                ccPair.overall_indexing_speed !== null &&
                ccPair.num_docs_indexed > 0 && (
                  <div className="ml-0.5 text-xs font-medium">
                    ({ccPair.overall_indexing_speed.toFixed(1)} docs / min)
                  </div>
                )}
            </div>
          </div>

          <div className="w-[200px]">
            <div className="text-sm font-medium mb-1">Last Indexed</div>
            <div className="text-sm text-text-default">
              {timeAgo(
                indexAttempts?.find((attempt) => attempt.status === "success")
                  ?.time_started
              ) ?? "-"}
            </div>
          </div>

          {ccPair.access_type === "sync" && (
            <>
              <div className="w-[200px]">
                {/* TODO: Remove className and switch to text03 once Text is fully integrated across this page */}
                <Text className="text-sm font-medium mb-1">
                  Permission Syncing
                </Text>
                {ccPair.permission_syncing ||
                ccPair.last_permission_sync_attempt_status ? (
                  <PermissionSyncStatus
                    status={ccPair.last_permission_sync_attempt_status}
                    errorMsg={ccPair.last_permission_sync_attempt_error_message}
                  />
                ) : (
                  <PermissionSyncStatus status={null} />
                )}
              </div>

              <div className="w-[200px]">
                {/* TODO: Remove className and switch to text03 once Text is fully integrated across this page */}
                <Text className="text-sm font-medium mb-1">Last Synced</Text>
                <Text className="text-sm text-text-default">
                  {ccPair.last_permission_sync_attempt_finished
                    ? timeAgo(ccPair.last_permission_sync_attempt_finished)
                    : timeAgo(ccPair.last_full_permission_sync) ?? "-"}
                </Text>
              </div>
            </>
          )}
        </div>
      </Card>

      {credentialTemplates[ccPair.connector.source] &&
        ccPair.is_editable_for_current_user && (
          <>
            <Title size="md" className="mt-10 mb-2">
              Credential
            </Title>

            <div className="mt-2">
              <CredentialSection
                ccPair={ccPair}
                sourceType={ccPair.connector.source}
                refresh={() => refresh()}
              />
            </div>
          </>
        )}

      {ccPair.connector.connector_specific_config &&
        Object.keys(ccPair.connector.connector_specific_config).length > 0 && (
          <>
            <Title size="md" className="mt-10 mb-2">
              Connector Configuration
            </Title>

            <Card className="px-8 py-4">
              <ConfigDisplay
                configEntries={buildConfigEntries(
                  ccPair.connector.connector_specific_config,
                  ccPair.connector.source
                )}
              />
            </Card>
          </>
        )}

      <div className="mt-6">
        <div className="flex">
          <AdvancedOptionsToggle
            showAdvancedOptions={showAdvancedOptions}
            setShowAdvancedOptions={setShowAdvancedOptions}
            title="Advanced"
          />
        </div>
        {showAdvancedOptions && (
          <div className="pb-16">
            {(pruneFreq || indexingStart || refreshFreq) && (
              <>
                <Title size="md" className="mt-3 mb-2">
                  Advanced Configuration
                </Title>
                <Card className="px-8 py-4">
                  <div>
                    <AdvancedConfigDisplay
                      pruneFreq={pruneFreq}
                      indexingStart={indexingStart}
                      refreshFreq={refreshFreq}
                      onRefreshEdit={handleRefreshEdit}
                      onPruningEdit={handlePruningEdit}
                    />
                  </div>
                </Card>
              </>
            )}

            <Title size="md" className="mt-6 mb-2">
              Indexing Attempts
            </Title>
            {indexAttempts && (
              <IndexAttemptsTable
                ccPair={ccPair}
                indexAttempts={indexAttempts}
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={goToPage}
              />
            )}
          </div>
        )}
      </div>
    </>
  );
}

export default function Page(props: { params: Promise<{ ccPairId: string }> }) {
  const params = use(props.params);
  const ccPairId = parseInt(params.ccPairId);

  return (
    <div className="mx-auto w-[800px]">
      <Main ccPairId={ccPairId} />
    </div>
  );
}
