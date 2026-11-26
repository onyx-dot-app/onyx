"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { useLayoutEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgSquare } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { formatDurationSeconds } from "@opal/time";
import { useActiveAgent } from "@/lib/agents/hooks";
import { useChatSubagents, useSubagentTranscript } from "@/lib/chat/hooks";
import {
  isLiveSubagent,
  SubagentPathContext,
  subagentStartedAt,
} from "@/lib/chat/subagents";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { PanelUrlBar } from "@/sections/output-panel/PanelUrlBar";
import HumanMessage from "@/lib/timeline/chat/message/HumanMessage";
import AgentResultsDivider from "@/lib/timeline/chat/message/AgentResultsDivider";
import AgentMessage from "@/lib/timeline/chat/message/messageComponents/AgentMessage";
import { ErrorBanner } from "@/lib/timeline/chat/message/Resubmit";

function FilledSquare(props: IconProps) {
  return <SvgSquare {...props} fill="currentColor" />;
}

interface SubagentBarProps {
  sessionId: string;
  agentId: string;
}

/**
 * The bar over a subagent's tab: its path, and while it runs its run time
 * and Stop, as the activity card's row has.
 */
export function SubagentBar({ sessionId, agentId }: SubagentBarProps) {
  const t = useTranslations("chat.activity.agents");
  const { agents, stopAgent } = useChatSubagents(sessionId, false);
  const agent = agents.find((candidate) => candidate.id === agentId);
  const live = agent !== undefined && isLiveSubagent(agent);
  const startedAt =
    live && agent ? (subagentStartedAt(agent) ?? undefined) : undefined;
  const elapsedSeconds = useStreamingDuration(live, startedAt);
  const name = agent ? agent.path.replace(/^\/root\//, "") : "";
  return (
    <PanelUrlBar displayUrl={agent?.path}>
      {startedAt !== undefined && (
        <Text
          font="secondary-body"
          color="text-03"
          wordWrap="whitespace-nowrap"
        >
          {formatDurationSeconds(Math.max(1, elapsedSeconds))}
        </Text>
      )}
      {live && (
        <Button
          icon={FilledSquare}
          variant="danger"
          prominence="tertiary"
          size="md"
          tooltip={t("stopTooltip")}
          aria-label={t("stop", { name })}
          onClick={() => void stopAgent(agentId)}
        />
      )}
    </PanelUrlBar>
  );
}

interface SubagentTranscriptProps {
  sessionId: string;
  agentId: string;
}

/**
 * A subagent's conversation, read-only: its instructions and its responses,
 * the running one live from its stream. It keeps to the end while it grows,
 * unless the user scrolled up.
 */
export function SubagentTranscript({
  sessionId,
  agentId,
}: SubagentTranscriptProps) {
  const t = useTranslations("chat.rightPanel.agentTab");
  const { agents } = useChatSubagents(sessionId, false);
  const agent = agents.find((candidate) => candidate.id === agentId);
  const streamId = agent?.stream_id ?? null;
  const { messages, loading, failed } = useSubagentTranscript(
    sessionId,
    agentId,
    streamId,
    agent?.latest_run_id ?? null
  );
  const persona = useActiveAgent();
  const scroller = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && atEnd.current) element.scrollTop = element.scrollHeight;
  }, [messages]);

  if (failed || (!loading && messages.length === 0))
    return (
      <Section padding={1}>
        <Text font="secondary-body" color="text-03">
          {failed ? t("failed") : t("empty")}
        </Text>
      </Section>
    );

  return (
    <div
      ref={scroller}
      className="absolute inset-0 overflow-y-auto px-4 py-3"
      onScroll={(event) => {
        const element = event.currentTarget;
        atEnd.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 32;
      }}
    >
      {/* Its spawns name agents below it */}
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
              if (message.type === "agent_results")
                return <AgentResultsDivider key={message.nodeId} />;
              if (message.type === "assistant" || message.type === "error")
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
    </div>
  );
}
