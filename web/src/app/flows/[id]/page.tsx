"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Text } from "@opal/components";
import { PageLoader, SettingsLayouts, toast } from "@opal/layouts";
import { SvgCheck, SvgPlayCircle, SvgUploadCloud, SvgZap } from "@opal/icons";
import {
  publishFlow,
  setFlowStatus,
  startRun,
  updateFlow,
} from "@/app/flows/api";
import { FlowCanvas } from "@/app/flows/components/FlowCanvas";
import { FlowStatusBadge } from "@/app/flows/components/StatusBadge";
import { NodeInspector } from "@/app/flows/components/NodeInspector";
import { NodePalette } from "@/app/flows/components/NodePalette";
import { ancestorsOf } from "@/app/flows/graphLayout";
import { FLOWS_API_BASE, FLOWS_PATH, flowRunPath } from "@/app/flows/constants";
import {
  addNode,
  isLastNode,
  removeNode,
  sameSpec,
  updateNode,
} from "@/app/flows/specEdits";
import type {
  FlowDetail,
  FlowNode,
  FlowNodeKind,
  FlowSpec,
} from "@/app/flows/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

/**
 * The flow editor.
 *
 * The draft spec lives in local state and is saved explicitly. Autosaving a
 * graph is a worse idea than it sounds: a half-wired node is a normal step on
 * the way to a finished flow, and the server rightly rejects one, so an
 * autosave would spend its time showing validation errors for work in
 * progress.
 */
export default function FlowEditorPage() {
  const t = useTranslations("flows.editor");
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const flowId = params.id;

  const {
    data: flow,
    error,
    isLoading,
    mutate,
  } = useSWR<FlowDetail>(`${FLOWS_API_BASE}/${flowId}`, errorHandlingFetcher);

  const [draft, setDraft] = useState<FlowSpec | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Adopt the server's spec once, and again whenever a save or publish
  // returns a newer one. Local edits are kept while the user is working.
  useEffect(() => {
    if (flow !== undefined && draft === null) setDraft(flow.spec);
  }, [flow, draft]);

  const dirty = useMemo(
    () => flow !== undefined && draft !== null && !sameSpec(flow.spec, draft),
    [flow, draft]
  );

  const selectedNode = useMemo(
    () => draft?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [draft, selectedNodeId]
  );

  const runAction = useCallback(
    async (action: () => Promise<void>, successMessage: string) => {
      setBusy(true);
      try {
        await action();
        await mutate();
        toast.success(successMessage);
      } catch (caught) {
        // Spec errors come back from the server with the offending node
        // named, so they are worth showing verbatim.
        toast.error(
          caught instanceof Error ? caught.message : t("genericError")
        );
      } finally {
        setBusy(false);
      }
    },
    [mutate, t]
  );

  const handleSave = useCallback(() => {
    if (draft === null) return;
    void runAction(async () => {
      await updateFlow(flowId, { spec: draft });
    }, t("toast.saved"));
  }, [draft, flowId, runAction, t]);

  const handlePublish = useCallback(() => {
    if (draft === null) return;
    void runAction(async () => {
      // Publish freezes whatever is stored, so an unsaved draft has to land
      // first or the user would publish the previous version.
      if (dirty) await updateFlow(flowId, { spec: draft });
      await publishFlow(flowId);
    }, t("toast.published"));
  }, [draft, dirty, flowId, runAction, t]);

  const handleToggleStatus = useCallback(() => {
    if (flow === undefined) return;
    const next = flow.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    void runAction(
      async () => {
        await setFlowStatus(flowId, next);
      },
      next === "ACTIVE" ? t("toast.activated") : t("toast.paused")
    );
  }, [flow, flowId, runAction, t]);

  const handleTestRun = useCallback(() => {
    if (draft === null) return;
    setBusy(true);
    void (async () => {
      try {
        if (dirty) await updateFlow(flowId, { spec: draft });
        const run = await startRun(flowId, { test: true });
        await mutate();
        router.push(flowRunPath(flowId, run.id));
      } catch (caught) {
        toast.error(
          caught instanceof Error ? caught.message : t("genericError")
        );
      } finally {
        setBusy(false);
      }
    })();
  }, [draft, dirty, flowId, mutate, router, t]);

  const handleAddNode = useCallback(
    (kind: FlowNodeKind) => {
      if (draft === null) return;
      const { spec, nodeId } = addNode(draft, kind, selectedNodeId);
      setDraft(spec);
      setSelectedNodeId(nodeId);
    },
    [draft, selectedNodeId]
  );

  const handleNodeChange = useCallback(
    (node: FlowNode) => {
      if (draft === null) return;
      setDraft(updateNode(draft, node.id, node));
    },
    [draft]
  );

  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      if (draft === null) return;
      setDraft(removeNode(draft, nodeId));
      setSelectedNodeId(null);
    },
    [draft]
  );

  if (isLoading || (flow === undefined && error === undefined)) {
    return <PageLoader />;
  }

  if (error !== undefined || flow === undefined || draft === null) {
    return (
      <SettingsLayouts.Root width="full">
        <SettingsLayouts.Body>
          <Text font="main-content-body" color="text-04">
            {t("loadFailed")}
          </Text>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root width="full">
      <SettingsLayouts.Header
        icon={SvgZap}
        title={flow.name}
        description={flow.description ?? undefined}
        backButton={() => router.push(FLOWS_PATH)}
        rightChildren={
          <div className="flex flex-row items-center gap-2">
            <FlowStatusBadge status={flow.status} />
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgPlayCircle}
              disabled={busy}
              onClick={handleTestRun}
            >
              {t("actions.test")}
            </Button>
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgCheck}
              disabled={busy || !dirty}
              onClick={handleSave}
            >
              {dirty ? t("actions.save") : t("actions.saved")}
            </Button>
            <Button
              variant="default"
              prominence="primary"
              icon={SvgUploadCloud}
              disabled={busy}
              onClick={handlePublish}
            >
              {t("actions.publish")}
            </Button>
            <Button
              variant={flow.status === "ACTIVE" ? "danger" : "action"}
              prominence="secondary"
              disabled={busy || flow.published_version === null}
              tooltip={
                flow.published_version === null
                  ? t("actions.publishFirst")
                  : undefined
              }
              onClick={handleToggleStatus}
            >
              {flow.status === "ACTIVE"
                ? t("actions.pause")
                : t("actions.activate")}
            </Button>
          </div>
        }
      >
        <NodePalette afterNodeId={selectedNodeId} onAdd={handleAddNode} />
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        <div className="flex flex-row h-[calc(100vh-16rem)] min-h-[32rem] gap-0 rounded-12 overflow-hidden border border-border-01">
          <FlowCanvas
            spec={draft}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            className="flex-1 min-w-0"
          />
          {selectedNode !== null ? (
            <NodeInspector
              node={selectedNode}
              isStart={selectedNode.id === draft.start}
              canDelete={!isLastNode(draft)}
              webhookSigningSecret={flow.webhook_signing_secret}
              mergeCandidates={ancestorsOf(draft, selectedNode.id)}
              onChange={handleNodeChange}
              onDelete={handleNodeDelete}
              className="w-80 shrink-0"
            />
          ) : (
            <aside className="w-80 shrink-0 flex items-center justify-center p-6 bg-background-neutral-00 border-s border-border-01">
              <Text font="main-ui-muted" color="text-03">
                {t("selectPrompt")}
              </Text>
            </aside>
          )}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
