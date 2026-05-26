"use client";

import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import { SvgRefreshCw } from "@opal/icons";
import { ThreeDotsLoader } from "@/components/Loading";
import { SourceIcon } from "@/components/SourceIcon";
import { CCPairStatus } from "@/components/Status";
import { ErrorCallout } from "@/components/ErrorCallout";
import Title from "@/components/ui/title";
import { Card } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { fetchConnectorIndexingStatus } from "@/lib/hooks";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import {
  ConnectorIndexingStatusLite,
  ConnectorIndexingStatusLiteResponse,
  ValidSources,
} from "@/lib/types";
import { localizeAndPrettify, timeAgo } from "@/lib/time";
import {
  buildCCPairInfoUrl,
  triggerIndexing,
} from "@/app/admin/connector/[ccPairId]/lib";
import {
  CCPairFullInfo,
  ConnectorCredentialPairStatus,
} from "@/app/admin/connector/[ccPairId]/types";

const CANVAS_STATUS_KEY = "tutor-instructor-canvas-knowledge";

function isCanvasConnectorStatus(
  status: ConnectorIndexingStatusLite | { id: number }
): status is ConnectorIndexingStatusLite {
  return "cc_pair_id" in status && status.source === ValidSources.Canvas;
}

function formatLastIndexed(lastIndexed: string | null | undefined) {
  return timeAgo(lastIndexed) ?? "Never";
}

function formatLastIndexedDetail(lastIndexed: string | null | undefined) {
  return lastIndexed
    ? localizeAndPrettify(lastIndexed)
    : "No index has run yet";
}

function KnowledgeMetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
}) {
  return (
    <Card className="min-h-[132px] px-6 py-5">
      <div className="text-xs font-medium uppercase tracking-wide text-subtle">
        {label}
      </div>
      <div className="mt-3 text-2xl font-semibold text-text-default">
        {value}
      </div>
      {detail && <div className="mt-2 text-sm text-subtle">{detail}</div>}
    </Card>
  );
}

function CanvasConnectorSelector({
  connectorStatuses,
  selectedCcPairId,
  onSelect,
}: {
  connectorStatuses: ConnectorIndexingStatusLite[];
  selectedCcPairId: number | null;
  onSelect: (ccPairId: number) => void;
}) {
  if (connectorStatuses.length <= 1) {
    return null;
  }

  return (
    <>
      <Title className="mb-2 mt-6" size="md">
        Canvas Knowledge Sources
      </Title>
      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Documents</TableHead>
              <TableHead>Last Indexed</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {connectorStatuses.map((status) => (
              <TableRow
                key={status.cc_pair_id}
                className={`cursor-pointer border-border hover:bg-accent-background ${
                  status.cc_pair_id === selectedCcPairId
                    ? "bg-background-settings-hover/20"
                    : ""
                }`}
                onClick={() => onSelect(status.cc_pair_id)}
              >
                <TableCell>{status.name || "Canvas"}</TableCell>
                <TableCell>{status.docs_indexed.toLocaleString()}</TableCell>
                <TableCell>{formatLastIndexed(status.last_success)}</TableCell>
                <TableCell>
                  <CCPairStatus
                    ccPairStatus={
                      status.last_finished_status !== null
                        ? status.cc_pair_status
                        : status.last_status === "not_started"
                          ? ConnectorCredentialPairStatus.SCHEDULED
                          : ConnectorCredentialPairStatus.INITIAL_INDEXING
                    }
                    inRepeatedErrorState={status.in_repeated_error_state}
                    lastIndexAttemptStatus={status.last_status}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}

export default function TutorInstructorKnowledge() {
  const vectorDbEnabled = useVectorDbEnabled();
  const [selectedCcPairId, setSelectedCcPairId] = useState<number | null>(null);
  const [isStartingReindex, setIsStartingReindex] = useState(false);

  const {
    data: connectorStatusResponses,
    error: connectorStatusError,
    isLoading: isLoadingConnectorStatuses,
    mutate: refreshConnectorStatuses,
  } = useSWR<ConnectorIndexingStatusLiteResponse[]>(
    vectorDbEnabled ? CANVAS_STATUS_KEY : null,
    () =>
      fetchConnectorIndexingStatus({
        source: ValidSources.Canvas,
        get_all_connectors: true,
      }),
    { refreshInterval: 30_000 }
  );

  const connectorStatuses = useMemo(() => {
    return (connectorStatusResponses ?? [])
      .flatMap((response) => response.indexing_statuses)
      .filter(isCanvasConnectorStatus)
      .filter((status) => status.is_editable)
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [connectorStatusResponses]);

  useEffect(() => {
    if (connectorStatuses.length === 0) {
      setSelectedCcPairId(null);
      return;
    }

    const selectedStillExists = connectorStatuses.some(
      (status) => status.cc_pair_id === selectedCcPairId
    );
    const firstConnectorStatus = connectorStatuses[0];
    if (!selectedStillExists && firstConnectorStatus) {
      setSelectedCcPairId(firstConnectorStatus.cc_pair_id);
    }
  }, [connectorStatuses, selectedCcPairId]);

  const selectedConnectorStatus = useMemo(() => {
    return (
      connectorStatuses.find(
        (status) => status.cc_pair_id === selectedCcPairId
      ) ?? null
    );
  }, [connectorStatuses, selectedCcPairId]);

  const {
    data: ccPair,
    error: ccPairError,
    isLoading: isLoadingCcPair,
    mutate: refreshCcPair,
  } = useSWR<CCPairFullInfo>(
    selectedCcPairId ? buildCCPairInfoUrl(selectedCcPairId) : null,
    errorHandlingFetcher,
    { refreshInterval: 5_000 }
  );

  const refreshCurrent = useCallback(async () => {
    await Promise.all([refreshConnectorStatuses(), refreshCcPair()]);
  }, [refreshCcPair, refreshConnectorStatuses]);

  const canForceReindex =
    !!ccPair &&
    !ccPair.indexing &&
    ccPair.status !== ConnectorCredentialPairStatus.PAUSED &&
    ccPair.status !== ConnectorCredentialPairStatus.INVALID &&
    ccPair.status !== ConnectorCredentialPairStatus.DELETING;

  const forceReindexTooltip = canForceReindex
    ? undefined
    : "Re-indexing is unavailable while this knowledge source is paused, invalid, deleting, or already indexing.";

  const handleForceReindex = useCallback(async () => {
    if (!ccPair || !canForceReindex) return;

    setIsStartingReindex(true);
    try {
      const result = await triggerIndexing(
        true,
        ccPair.connector.id,
        ccPair.credential.id,
        ccPair.id
      );

      if (result.success) {
        toast.success("Canvas knowledge re-index started successfully");
      } else {
        toast.error(result.message || "Failed to start re-indexing");
      }
      await refreshCurrent();
    } catch (error) {
      console.error("Failed to start Canvas knowledge re-index", error);
      toast.error("Failed to start re-indexing");
    } finally {
      setIsStartingReindex(false);
    }
  }, [canForceReindex, ccPair, refreshCurrent]);

  if (!vectorDbEnabled) {
    return (
      <div className="flex h-full min-h-0 w-full items-center justify-center bg-background-tint-01 p-6">
        <Callout type="warning" title="Vector search disabled">
          Canvas knowledge requires vector search.
        </Callout>
      </div>
    );
  }

  if (isLoadingConnectorStatuses) {
    return (
      <div className="flex h-full min-h-0 w-full items-center justify-center bg-background-tint-01">
        <ThreeDotsLoader />
      </div>
    );
  }

  if (connectorStatusError) {
    return (
      <div className="flex h-full min-h-0 w-full bg-background-tint-01 p-6">
        <div className="mx-auto w-full max-w-[800px]">
          <ErrorCallout
            errorTitle="Failed to fetch Canvas knowledge sources"
            errorMsg={connectorStatusError.message}
          />
        </div>
      </div>
    );
  }

  if (connectorStatuses.length === 0) {
    return (
      <div className="flex h-full min-h-0 w-full bg-background-tint-01 p-6">
        <div className="mx-auto w-full max-w-[800px]">
          <Callout type="notice" title="No Canvas knowledge source found">
            No editable Canvas connector is available for this course.
          </Callout>
        </div>
      </div>
    );
  }

  if (ccPairError) {
    return (
      <div className="flex h-full min-h-0 w-full bg-background-tint-01 p-6">
        <div className="mx-auto w-full max-w-[800px]">
          <ErrorCallout
            errorTitle="Failed to fetch Canvas knowledge details"
            errorMsg={ccPairError.message}
          />
        </div>
      </div>
    );
  }

  if (isLoadingCcPair || !ccPair) {
    return (
      <div className="flex h-full min-h-0 w-full items-center justify-center bg-background-tint-01">
        <ThreeDotsLoader />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-y-auto bg-background-tint-01">
      <div className="mx-auto w-full max-w-[800px] p-4 md:p-6">
        <div className="flex min-h-16 items-center justify-between gap-4 border-b border-neutral-200 pb-3 dark:border-neutral-600">
          <div className="flex min-w-0 items-center gap-3">
            <SourceIcon iconSize={32} sourceType={ccPair.connector.source} />
            <div className="min-w-0">
              <div className="truncate text-xl font-semibold text-text-default">
                Canvas Knowledge
              </div>
              <div className="truncate text-sm text-subtle">{ccPair.name}</div>
            </div>
          </div>

          <Button
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={!canForceReindex || isStartingReindex}
            tooltip={forceReindexTooltip}
            onClick={() => void handleForceReindex()}
          >
            Force Re-Index
          </Button>
        </div>

        <CanvasConnectorSelector
          connectorStatuses={connectorStatuses}
          selectedCcPairId={selectedCcPairId}
          onSelect={setSelectedCcPairId}
        />

        {ccPair.status === ConnectorCredentialPairStatus.INVALID && (
          <div className="mt-6">
            <Callout type="warning" title="Knowledge source needs attention">
              This Canvas knowledge source cannot be re-indexed until its setup
              is fixed.
            </Callout>
          </div>
        )}

        <Title className="mb-2 mt-6" size="md">
          Knowledge Status
        </Title>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <KnowledgeMetricCard
            label="Documents Indexed"
            value={ccPair.num_docs_indexed.toLocaleString()}
            detail={
              ccPair.status ===
                ConnectorCredentialPairStatus.INITIAL_INDEXING &&
              ccPair.overall_indexing_speed !== null &&
              ccPair.num_docs_indexed > 0
                ? `${ccPair.overall_indexing_speed.toFixed(1)} docs / min`
                : undefined
            }
          />

          <KnowledgeMetricCard
            label="Last Indexed"
            value={formatLastIndexed(ccPair.last_indexed)}
            detail={formatLastIndexedDetail(ccPair.last_indexed)}
          />

          <KnowledgeMetricCard
            label="Status"
            value={
              <CCPairStatus
                ccPairStatus={ccPair.status}
                inRepeatedErrorState={ccPair.in_repeated_error_state}
                lastIndexAttemptStatus={selectedConnectorStatus?.last_status}
              />
            }
            detail={
              ccPair.indexing
                ? "Indexing is currently running"
                : "Ready for tutor retrieval"
            }
          />
        </div>
      </div>
    </div>
  );
}
