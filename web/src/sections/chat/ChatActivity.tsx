"use client";

import { useContext, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useFormatter, useTranslations } from "next-intl";
import { Button, LineItemButton, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgActivity,
  SvgAlertCircle,
  SvgCheckCircle,
  SvgChevronDown,
  SvgChevronRight,
  SvgCircle,
  SvgFiles,
  SvgHelpCircle,
  SvgLoader,
  SvgPauseCircle,
  SvgStopCircle,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";
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
import type { ChatSubagent } from "@/lib/chat/types";

function SpinningLoader({ className, ...props }: IconProps) {
  return (
    <SvgLoader
      {...props}
      className={cn(className, "motion-safe:animate-spin")}
    />
  );
}

const STATUS_ICONS = {
  starting: SvgCircle,
  running: SpinningLoader,
  suspended: SvgPauseCircle,
  complete: SvgCheckCircle,
  limit: SvgAlertCircle,
  cancelled: SvgStopCircle,
  stopped: SvgStopCircle,
  error: SvgXCircle,
} satisfies Record<
  NonNullable<ChatSubagent["status"]> | "starting" | "stopped",
  IconFunctionComponent
>;

function isFinished(agent: ChatSubagent): boolean {
  return (
    agent.stopped_by_user ||
    (agent.status !== null &&
      agent.status !== "running" &&
      agent.status !== "suspended")
  );
}

function agentState(agent: ChatSubagent): keyof typeof STATUS_ICONS {
  if (agent.stopped_by_user) return "stopped";
  return agent.status ?? "starting";
}

interface ChatActivityProps {
  sessionId: string;
}

/**
 * The chat's activity card, toggled from its header: what waits for the user,
 * the background agents and their status, and the published files. It stays
 * open until its header button closes it, and shows only once the chat has any
 * of them. A waiting request scrolls to its card; files open in the right
 * panel. The card pins to the chat region's top end, under its header, so the
 * header's buttons stay in place. With no output panel open and a workspace at
 * least 64rem wide, the chat's content narrows for it; otherwise it floats
 * over the chat's end.
 */
export default function ChatActivity({ sessionId }: ChatActivityProps) {
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
  const agents = useChatSubagents(sessionId, useCurrentChatState() !== "input");
  const files = usePublishedFiles("current");
  // Finished agents fold under one row, as their own list
  const [showFinished, setShowFinished] = useState(false);
  const finishedAgents = agents.filter(isFinished);
  const liveAgents = agents.filter((agent) => !isFinished(agent));
  const agentRow = (agent: ChatSubagent) => {
    const state = agentState(agent);
    return (
      <LineItemButton
        key={agent.id}
        presentational
        icon={STATUS_ICONS[state]}
        title={agent.path.replace(/^\/root\//, "")}
        titleMaxLines={1}
        rightChildren={
          <Text font="secondary-body" color="text-03">
            {t(`agents.status.${state}`)}
          </Text>
        }
      />
    );
  };
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
                    {t("agents.title")}
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
