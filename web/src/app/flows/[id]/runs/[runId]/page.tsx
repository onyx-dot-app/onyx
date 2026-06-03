"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Text } from "@opal/components";
import { PageLoader, SettingsLayouts } from "@opal/layouts";
import { SvgZap } from "@opal/icons";
import { FlowCanvas } from "@/app/flows/components/FlowCanvas";
import { RunStatusBadge } from "@/app/flows/components/StatusBadge";
import {
  FLOWS_API_BASE,
  RUN_POLL_INTERVAL_MS,
  flowDetailPath,
} from "@/app/flows/constants";
import type {
  FlowDetail,
  FlowNodeRunStatus,
  NodeRun,
  RunDetail,
} from "@/app/flows/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

/**
 * One run, drawn on the same canvas as the editor.
 *
 * Reusing the canvas is the point: the shape you built is the shape you
 * debug, with each node wearing the outcome it had. Clicking a node shows
 * what went in and what came out, which is the question a failed run
 * actually raises.
 */
export default function FlowRunPage() {
  const t = useTranslations("flows.run");
  const router = useRouter();
  const params = useParams<{ id: string; runId: string }>();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const { data: flow } = useSWR<FlowDetail>(
    `${FLOWS_API_BASE}/${params.id}`,
    errorHandlingFetcher
  );

  const { data: run, isLoading } = useSWR<RunDetail>(
    `${FLOWS_API_BASE}/${params.id}/runs/${params.runId}`,
    errorHandlingFetcher,
    {
      // Poll only while there is something left to watch, so a finished run
      // stops costing requests the moment it settles.
      refreshInterval: (latest) =>
        latest !== undefined &&
        (latest.status === "QUEUED" || latest.status === "RUNNING")
          ? RUN_POLL_INTERVAL_MS
          : 0,
    }
  );

  const statusByNode = useMemo(() => {
    const statuses: Record<string, FlowNodeRunStatus> = {};
    for (const nodeRun of run?.node_runs ?? []) {
      // A fanned-out node has one row per item. The worst outcome wins, since
      // that is the one worth looking at.
      const existing = statuses[nodeRun.node_id];
      statuses[nodeRun.node_id] = worseOf(existing, nodeRun.status);
    }
    return statuses;
  }, [run]);

  const selectedRuns = useMemo(
    () =>
      (run?.node_runs ?? []).filter(
        (nodeRun) => nodeRun.node_id === selectedNodeId
      ),
    [run, selectedNodeId]
  );

  if (isLoading || run === undefined || flow === undefined) {
    return <PageLoader />;
  }

  return (
    <SettingsLayouts.Root width="full">
      <SettingsLayouts.Header
        icon={SvgZap}
        title={t("title", { flow: flow.name })}
        backButton={() => router.push(flowDetailPath(params.id))}
        rightChildren={<RunStatusBadge status={run.status} />}
      >
        {run.error_detail !== null ? (
          <Text font="main-ui-body" color="text-04">
            {run.error_detail}
          </Text>
        ) : null}
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        <div className="flex flex-row h-[calc(100vh-16rem)] min-h-[32rem] rounded-12 overflow-hidden border border-border-01">
          <FlowCanvas
            spec={flow.spec}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            runStatusByNode={statusByNode}
            className="flex-1 min-w-0"
          />
          <aside className="w-96 shrink-0 flex flex-col gap-3 p-4 overflow-y-auto bg-background-neutral-00 border-s border-border-01">
            {selectedNodeId === null ? (
              <Text font="main-ui-muted" color="text-03">
                {t("selectPrompt")}
              </Text>
            ) : selectedRuns.length === 0 ? (
              <Text font="main-ui-muted" color="text-03">
                {t("notRun")}
              </Text>
            ) : (
              selectedRuns.map((nodeRun) => (
                <NodeRunDetails
                  key={`${nodeRun.node_id}-${nodeRun.item_index}`}
                  nodeRun={nodeRun}
                  showItemIndex={selectedRuns.length > 1}
                />
              ))
            )}
          </aside>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function NodeRunDetails({
  nodeRun,
  showItemIndex,
}: {
  nodeRun: NodeRun;
  showItemIndex: boolean;
}) {
  const t = useTranslations("flows.run");

  return (
    <div
      data-testid="node-run-item"
      className="flex flex-col gap-2 pb-3 border-b border-border-01"
    >
      {showItemIndex ? (
        <Text font="figure-small-label" color="text-03">
          {t("item", { index: nodeRun.item_index })}
        </Text>
      ) : null}

      {nodeRun.error_detail !== null ? (
        <div className="p-2 rounded-08 bg-status-error-01">
          <Text font="main-ui-body" color="text-04">
            {nodeRun.error_detail}
          </Text>
        </div>
      ) : null}

      {nodeRun.input !== null ? (
        <JsonBlock label={t("input")} value={nodeRun.input} />
      ) : null}
      <JsonBlock label={t("output")} value={nodeRun.output} />
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex flex-col gap-1">
      <Text font="figure-small-label" color="text-03">
        {label}
      </Text>
      <pre className="p-2 rounded-08 bg-background-tint-02 overflow-x-auto">
        <Text font="main-ui-mono" color="text-04">
          {JSON.stringify(value, null, 2) ?? "null"}
        </Text>
      </pre>
    </div>
  );
}

/** Worst-first ordering, so a fanned-out node reports its unhappiest item. */
const SEVERITY = {
  FAILED: 3,
  RUNNING: 2,
  SUCCEEDED: 1,
  SKIPPED: 0,
} satisfies Record<FlowNodeRunStatus, number>;

function worseOf(
  existing: FlowNodeRunStatus | undefined,
  candidate: FlowNodeRunStatus
): FlowNodeRunStatus {
  if (existing === undefined) return candidate;
  return SEVERITY[candidate] > SEVERITY[existing] ? candidate : existing;
}
