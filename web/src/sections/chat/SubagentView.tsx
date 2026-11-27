"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { useLayoutEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgArrowUpLeft, SvgSquare } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { ChatMessageLoader } from "@opal/loaders";
import { formatDurationSeconds } from "@opal/time";
import { cn } from "@opal/utils";
import type { MinimalOnyxDocument } from "@/lib/search/types";
import { useActiveAgent } from "@/lib/agents/hooks";
import { useChatSubagents, useSubagentTranscript } from "@/lib/chat/hooks";
import { CHAT_COLUMN_WIDTH, CHAT_GUTTER } from "@/lib/chat/layout";
import {
  isLiveSubagent,
  SubagentPathContext,
  subagentStartedAt,
  subagentState,
  useSubagentNavigation,
} from "@/lib/chat/subagents";
import type { ChatSubagent } from "@/lib/chat/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import HumanMessage from "@/lib/timeline/chat/message/HumanMessage";
import AgentMessage from "@/lib/timeline/chat/message/messageComponents/AgentMessage";
import { ErrorBanner } from "@/lib/timeline/chat/message/Resubmit";

function FilledSquare(props: IconProps) {
  return <SvgSquare {...props} fill="currentColor" />;
}

const MAX_PARENT_TITLE = 32;

interface ParentDividerProps {
  // The parent chat's title; none while it has none
  parentTitle: string | null;
}

/** T3 Code's "Subagent of" divider: a pill that opens the parent chat. */
function ParentDivider({ parentTitle }: ParentDividerProps) {
  const t = useTranslations("chat.subagents.view");
  const { openParent } = useSubagentNavigation();
  return (
    <div className="pt-3 pb-2 sm:pt-4">
      <Section flexDirection="row" gap={2} height="fit">
        <span aria-hidden className="h-px flex-1 bg-border-01" />
        <Button
          icon={STEP_ICONS.agent}
          prominence="secondary"
          rounding="full"
          size="xs"
          tooltip={t("openParentChat")}
          aria-label={t("openParentChat")}
          onClick={openParent}
        >
          {parentTitle
            ? t("parentOf", {
                // The button does not truncate; this fits a phone's width
                title:
                  parentTitle.length > MAX_PARENT_TITLE
                    ? `${parentTitle.slice(0, MAX_PARENT_TITLE - 1)}…`
                    : parentTitle,
              })
            : t("parent")}
        </Button>
        <span aria-hidden className="h-px flex-1 bg-border-01" />
      </Section>
    </div>
  );
}

interface SubagentViewProps {
  sessionId: string;
  agentId: string;
  parentTitle: string | null;
  // Opens a cited file's preview, as the main chat does
  setPresentingDocument: (document: MinimalOnyxDocument) => void;
}

/**
 * A subagent of the open chat in the main view, as T3 Code shows one: the
 * divider that opens the parent, then its conversation, read-only, the
 * running response live from its stream. It keeps to the end while it grows,
 * unless the user scrolled up.
 */
export function SubagentView({
  sessionId,
  agentId,
  parentTitle,
  setPresentingDocument,
}: SubagentViewProps) {
  const t = useTranslations("chat.subagents.view");
  const { agents } = useChatSubagents(sessionId, false);
  const agent = agents.find((candidate) => candidate.id === agentId);
  const { messages, loading, failed } = useSubagentTranscript(
    sessionId,
    agentId,
    agent?.stream_id ?? null,
    agent?.latest_run_id ?? null
  );
  const persona = useActiveAgent();
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  // Steps reveal one at a time, so the content grows between message updates
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || !content.current) return;
    const observer = new ResizeObserver(() => {
      // Content that fits has no scroll to say the reader left the end
      if (element.scrollHeight <= element.clientHeight) atEnd.current = true;
      if (atEnd.current) element.scrollTop = element.scrollHeight;
    });
    observer.observe(content.current);
    return () => observer.disconnect();
  }, []);
  // A failed refresh keeps the transcript it has
  const empty = messages.length === 0 && (failed || !loading);

  return (
    <div
      ref={scroller}
      data-testid="subagent-view"
      // Makes room for a docked activity card, as the chat does (`AppChrome`)
      data-chat-scroll
      className="w-full flex-1 min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
      onScroll={(event) => {
        const element = event.currentTarget;
        atEnd.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 32;
      }}
    >
      <div ref={content} className={cn("w-full", CHAT_GUTTER)}>
        <div className={cn("w-full mx-auto pb-8", CHAT_COLUMN_WIDTH)}>
          <ParentDivider parentTitle={parentTitle} />
          {messages.length === 0 && loading && !failed ? (
            <Section gap={1} alignItems="stretch" height="fit">
              <ChatMessageLoader orientation="end" />
              <ChatMessageLoader orientation="start" />
            </Section>
          ) : empty ? (
            <Section padding={1} height="fit">
              <Text font="secondary-body" color="text-03">
                {failed ? t("failed") : t("empty")}
              </Text>
            </Section>
          ) : (
            // Its spawns name agents below it
            <SubagentPathContext.Provider value={agent?.path ?? "/root"}>
              <Section gap={1} alignItems="stretch" height="auto">
                {persona &&
                  messages.map((message) => {
                    if (message.type === "user")
                      return (
                        <HumanMessage
                          key={message.nodeId}
                          content={message.message}
                          files={message.files}
                          nodeId={message.nodeId}
                        />
                      );
                    if (
                      message.type === "assistant" ||
                      message.type === "error"
                    )
                      return (
                        <div key={message.nodeId}>
                          {(message.type !== "error" ||
                            message.packets.length > 0) && (
                            <AgentMessage
                              rawPackets={message.packets}
                              packetCount={message.packets.length}
                              chatState={{
                                agent: persona,
                                docs: message.documents,
                                citations: message.citations,
                                setPresentingDocument,
                              }}
                              nodeId={message.nodeId}
                              llmManager={null}
                              hideFooter
                              disableTTS
                            />
                          )}
                          {message.type === "error" && (
                            <ErrorBanner
                              error={message.errorMessage ?? ""}
                              errorCode={message.errorCode ?? undefined}
                              isRetryable={false}
                              details={message.errorDetails ?? undefined}
                            />
                          )}
                        </div>
                      );
                    return null;
                  })}
              </Section>
            </SubagentPathContext.Provider>
          )}
        </div>
      </div>
      {/* Room for the bar laid over the view's end */}
      <div aria-hidden className="h-(--app-composer-height)" />
    </div>
  );
}

interface StatusText {
  // With its time, where it has one
  text: string;
  // Without its time, so it does not tick
  announcement: string;
}

/** The agent's state as the bar says it. */
function useStatusText(agent: ChatSubagent): StatusText {
  const t = useTranslations("chat.subagents");
  const live = isLiveSubagent(agent);
  const startedAt = live ? (subagentStartedAt(agent) ?? undefined) : undefined;
  const elapsed = useStreamingDuration(live, startedAt);
  const state = subagentState(agent);
  const label = t(`status.${state}`);
  const text =
    (state === "running" || state === "waiting") && startedAt !== undefined
      ? t(`timedStatus.${state}`, {
          elapsed: formatDurationSeconds(Math.max(1, elapsed)),
        })
      : state === "completed" && agent.duration_seconds !== null
        ? t("timedStatus.completed", {
            elapsed: formatDurationSeconds(Math.max(1, agent.duration_seconds)),
          })
        : label;
  return { text, announcement: label };
}

interface SubagentStatusProps {
  agent: ChatSubagent;
}

/** The bar's lead: the model, then the state, and its announcement. */
function SubagentStatus({ agent }: SubagentStatusProps) {
  const t = useTranslations("chat.subagents.bar");
  const { text, announcement } = useStatusText(agent);
  return (
    <>
      <span role="status" className="sr-only">
        {agent.model
          ? t("announcement", { model: agent.model, status: announcement })
          : t("announcementUnnamed", { status: announcement })}
      </span>
      {agent.model && (
        <Text font="main-ui-body" color="text-05" maxLines={1}>
          {agent.model}
        </Text>
      )}
      <span aria-hidden className="min-w-0 tabular-nums">
        <Text font="main-ui-muted" color="text-03" maxLines={1}>
          {text}
        </Text>
      </span>
    </>
  );
}

interface SubagentBarProps {
  sessionId: string;
  agentId: string;
}

/**
 * What stands where the composer would for a subagent, as T3 Code's
 * subagent bar: its model and state, that it runs on its own, its Stop while
 * it runs, and the way back to the parent chat.
 */
export function SubagentBar({ sessionId, agentId }: SubagentBarProps) {
  const t = useTranslations("chat.subagents.bar");
  const tAgents = useTranslations("chat.activity.agents");
  const { agents, stopAgent } = useChatSubagents(sessionId, false);
  const { openParent } = useSubagentNavigation();
  const agent = agents.find((candidate) => candidate.id === agentId);
  const live = agent !== undefined && isLiveSubagent(agent);
  return (
    <div
      data-testid="subagent-bar"
      className="w-full rounded-16 bg-background-neutral-00 shadow-box-01 py-2 ps-5 pe-2"
    >
      <Section flexDirection="row" gap={3} height="fit" minHeight={2}>
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={3}
          height="fit"
          grow={1}
        >
          {agent && <SubagentStatus agent={agent} />}
        </Section>
        {agent && (
          <span className="shrink-0 max-sm:sr-only">
            <Text
              font="main-ui-muted"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
              {t("runsOnItsOwn")}
            </Text>
          </span>
        )}
        {live && (
          <Button
            icon={FilledSquare}
            variant="danger"
            prominence="tertiary"
            size="sm"
            tooltip={tAgents("stopTooltip")}
            aria-label={tAgents("stop", {
              name: agent.path.replace(/^\/root\//, ""),
            })}
            onClick={() => void stopAgent(agentId)}
          />
        )}
        <Button
          icon={SvgArrowUpLeft}
          prominence="tertiary"
          size="sm"
          onClick={openParent}
        >
          {t("openParent")}
        </Button>
      </Section>
    </div>
  );
}
