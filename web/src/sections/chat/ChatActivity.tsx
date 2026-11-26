"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useFormatter, useTranslations } from "next-intl";
import { Button, LineItemButton, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { Section } from "@opal/layouts";
import {
  SvgActivity,
  SvgAlertCircle,
  SvgBranch,
  SvgCheckCircle,
  SvgChevronDown,
  SvgChevronRight,
  SvgFiles,
  SvgHelpCircle,
  SvgSquare,
  SvgStopCircle,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { formatDurationSeconds } from "@opal/time";
import {
  useCurrentChatState,
  useCurrentMessageTree,
  useRightPanelShown,
} from "@/app/app/stores/useChatSessionStore";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";
import { CHAT_FILES_PANEL } from "@/sections/chat/ChatRightPanel";
import { useChatSubagents, usePublishedFiles } from "@/lib/chat/hooks";
import {
  readWaitingToolRequests,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";
import type { ChatSubagent, RunStatus } from "@/lib/chat/types";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";

/** A live agent: the agent glyph with a small blue dot, as T3 Code's. */
function LiveAgentIcon(props: IconProps) {
  return (
    <span className="relative inline-block">
      <SvgBranch {...props} />
      <span
        aria-hidden
        className="absolute -end-0.5 -top-0.5 size-1.5 rounded-full bg-status-info-05"
      />
    </span>
  );
}

function FilledSquare(props: IconProps) {
  return <SvgSquare {...props} fill="currentColor" />;
}

type FinishedState = Exclude<RunStatus, "running" | "suspended"> | "stopped";

const FINISHED_ICONS = {
  complete: SvgCheckCircle,
  limit: SvgAlertCircle,
  cancelled: SvgStopCircle,
  stopped: SvgStopCircle,
  error: SvgXCircle,
} satisfies Record<FinishedState, IconFunctionComponent>;

/** The agent's finished state, or null while it runs or starts. */
function finishedState(agent: ChatSubagent): FinishedState | null {
  if (agent.stopped_by_user) return "stopped";
  if (
    agent.status === null ||
    agent.status === "running" ||
    agent.status === "suspended"
  )
    return null;
  return agent.status;
}

function isFinished(agent: ChatSubagent): boolean {
  return finishedState(agent) !== null;
}

// A row's run counts as new when it started this long before the card mounted
const NEW_RUN_WINDOW_MS = 10_000;

interface AgentRowProps {
  agent: ChatSubagent;
  onStop: (agentId: string) => Promise<void>;
}

/**
 * One agent, as T3 Code's lineage rows: a live agent shows how long its run
 * has worked, which hover or focus swaps for its Stop; a finished agent shows
 * its outcome.
 */
function AgentRow({ agent, onStop }: AgentRowProps) {
  const t = useTranslations("chat.activity.agents");
  const finished = finishedState(agent);
  const name = agent.path.replace(/^\/root\//, "");
  const parsed = agent.started_at ? Date.parse(agent.started_at) : NaN;
  const startedAt =
    finished === null && !Number.isNaN(parsed) ? parsed : undefined;
  const elapsedSeconds = useStreamingDuration(finished === null, startedAt);
  const row = (
    <LineItemButton
      presentational
      icon={finished === null ? LiveAgentIcon : FINISHED_ICONS[finished]}
      title={name}
      titleMaxLines={1}
      rightChildren={
        finished !== null ? (
          <Text
            as="p"
            font="secondary-body"
            color="text-03"
            wordWrap="whitespace-nowrap"
          >
            {t(`status.${finished}`)}
          </Text>
        ) : (
          // The Stop sits over the time, so it stays in the tab order while
          // hidden; on a touch screen it shows in place of the time
          <div className="relative min-w-6">
            <Hoverable.Item group="chatActivityAgent" variant="appear-on-rest">
              <div className="text-end no-hover:invisible">
                {/* Plain text: a button label animates its changes, so each
                    tick would flash */}
                {startedAt !== undefined && (
                  <Text
                    as="p"
                    font="secondary-body"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {/* The server's clock can run ahead of the browser's */}
                    {formatDurationSeconds(Math.max(1, elapsedSeconds))}
                  </Text>
                )}
              </div>
            </Hoverable.Item>
            <div className="absolute end-0 top-1/2 -translate-y-1/2">
              <Hoverable.Item
                group="chatActivityAgent"
                variant="appear-on-hover"
              >
                <Button
                  icon={FilledSquare}
                  variant="danger"
                  prominence="tertiary"
                  size="xs"
                  tooltip={t("stopTooltip")}
                  aria-label={t("stop", { name })}
                  onClick={() => void onStop(agent.id)}
                />
              </Hoverable.Item>
            </div>
          </div>
        )
      }
    />
  );
  return finished === null ? (
    <Hoverable.Root group="chatActivityAgent">{row}</Hoverable.Root>
  ) : (
    row
  );
}

interface ChatActivityProps {
  sessionId: string;
  // Lists the published files, whose row opens the chat's Files panel; a
  // page without that panel, such as the extension's, leaves them out
  showFiles?: boolean;
}

const NO_FILES: PublishedFile[] = [];

/**
 * The chat's activity card, toggled from its header: what waits for the user,
 * the background agents with their run time and Stop, and the published
 * files. Agents that start open it; it stays open until its header button
 * closes it, and shows only once the chat has any of them. A waiting request
 * scrolls to its card; files open in the right panel. The card pins to the
 * chat region's top end, under its header, so the header's buttons stay in
 * place. With no output panel open and a workspace at
 * least 64rem wide, the chat's content narrows for it; otherwise it floats
 * over the chat's end.
 */
export default function ChatActivity({
  sessionId,
  showFiles = true,
}: ChatActivityProps) {
  const t = useTranslations("chat.activity");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const tree = useCurrentMessageTree();
  // Requests that this client already decided or answered leave at once, as
  // their cards do, before the server's resolution arrives
  const localStatuses = useToolRequestUi((state) => state.localStatuses);
  const localAnswers = useToolRequestUi((state) => state.localAnswers);
  const waiting = useMemo(
    () =>
      (tree ? readWaitingToolRequests(tree) : []).filter((item) =>
        item.kind === "approval"
          ? (localStatuses.get(item.request.approval_id) ?? "pending") ===
            "pending"
          : (localAnswers.get(item.request.question_request_id)?.kind ??
              "pending") === "pending"
      ),
    [tree, localStatuses, localAnswers]
  );
  const streaming = useCurrentChatState() !== "input";
  const { agents, loaded, stopAgent } = useChatSubagents(sessionId, streaming);
  const publishedFiles = usePublishedFiles("current");
  const files = showFiles ? publishedFiles : NO_FILES;
  // Finished agents fold under one row, as their own list
  const [showFinished, setShowFinished] = useState(false);
  const finishedAgents = agents.filter(isFinished);
  const liveAgents = agents.filter((agent) => !isFinished(agent));
  const agentRow = (agent: ChatSubagent) => (
    <AgentRow key={agent.id} agent={agent} onStop={stopAgent} />
  );
  // Agents that start while the chat shows open the card, once per run of
  // agents. In the first list, only runs that started just before the card
  // mounted count as new: a new chat's reply can start agents before that
  // list arrives, while a chat opened later has older runs.
  const [mountedAt] = useState(() => Date.now());
  const liveCount = loaded ? liveAgents.length : null;
  const newAtLoad =
    loaded &&
    liveAgents.some(
      (agent) =>
        agent.started_at !== null &&
        Date.parse(agent.started_at) > mountedAt - NEW_RUN_WINDOW_MS
    );
  const previousLiveCount = useRef<number | null>(null);
  useEffect(() => {
    if (liveCount === null) return;
    const previous = previousLiveCount.current;
    if ((previous === null ? newAtLoad : previous === 0) && liveCount > 0)
      setOpen(true);
    previousLiveCount.current = liveCount;
  }, [liveCount, newAtLoad]);
  const activitySlot = useContext(AppWorkspaceElementsContext)?.activitySlot;
  // Beside a closed output panel, the chat makes room for the card
  const docked = !useRightPanelShown();

  if (waiting.length === 0 && agents.length === 0 && files.length === 0)
    return null;

  const nudge = (requestId: string) => () =>
    useToolRequestUi.getState().nudgeRequest(requestId);
  return (
    <>
      <Button
        icon={SvgActivity}
        prominence="tertiary"
        tooltip={t("trigger.label")}
        aria-label={t("trigger.label")}
        aria-expanded={open}
        aria-controls="chat-activity"
        onClick={() => setOpen((value) => !value)}
      />
      {open &&
        activitySlot &&
        createPortal(
          <div
            id="chat-activity"
            role="region"
            aria-label={t("trigger.label")}
            // Docked, it marks the workspace so the chat's content and
            // footer make room for it (`AppChrome`)
            data-activity-docked={docked ? "" : undefined}
            className="absolute end-3 top-14 z-30 max-h-[calc(100%-4.25rem)] w-80 max-w-[calc(100%-1.5rem)] overflow-y-auto rounded-12 border border-border-01 bg-background-neutral-00 p-2 shadow-box"
          >
            <Section gap={0.75} alignItems="stretch" height="auto">
              {waiting.length > 0 && (
                <Section gap={0.5} alignItems="stretch" height="auto">
                  <Text as="p" font="secondary-action" color="text-03">
                    {t("needsYou.title")}
                  </Text>
                  {waiting.map((item) =>
                    item.kind === "approval" ? (
                      <LineItemButton
                        key={item.request.approval_id}
                        icon={SvgAlertCircle}
                        title={t("needsYou.approval", {
                          tool: item.request.display_name,
                        })}
                        description={item.request.agent_name ?? undefined}
                        onClick={nudge(item.request.approval_id)}
                      />
                    ) : (
                      <LineItemButton
                        key={item.request.question_request_id}
                        icon={SvgHelpCircle}
                        title={t("needsYou.question")}
                        description={item.request.questions[0]?.question}
                        onClick={nudge(item.request.question_request_id)}
                      />
                    )
                  )}
                </Section>
              )}
              {agents.length > 0 && (
                <Section gap={0.5} alignItems="stretch" height="auto">
                  <Text as="p" font="secondary-action" color="text-03">
                    {liveAgents.length > 0
                      ? t("agents.titleRunning", { count: liveAgents.length })
                      : t("agents.title")}
                  </Text>
                  {liveAgents.map(agentRow)}
                  {finishedAgents.length > 0 && (
                    <LineItemButton
                      icon={showFinished ? SvgChevronDown : SvgChevronRight}
                      title={t("agents.finished")}
                      aria-expanded={showFinished}
                      rightChildren={
                        <Text font="secondary-body" color="text-03">
                          {format.number(finishedAgents.length)}
                        </Text>
                      }
                      onClick={() => setShowFinished((value) => !value)}
                    />
                  )}
                  {showFinished && finishedAgents.map(agentRow)}
                </Section>
              )}
              {files.length > 0 && (
                <Section gap={0.5} alignItems="stretch" height="auto">
                  <Text as="p" font="secondary-action" color="text-03">
                    {t("files.title")}
                  </Text>
                  <LineItemButton
                    icon={SvgFiles}
                    title={t("files.viewAll", { count: files.length })}
                    onClick={CHAT_FILES_PANEL.showFiles}
                  />
                </Section>
              )}
            </Section>
          </div>,
          activitySlot
        )}
    </>
  );
}
