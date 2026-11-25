"use client";

import React, { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Presence } from "@opal/components";
import { SvgListTree } from "@opal/icons";
import { Section } from "@opal/layouts";
import { prefersReducedMotion } from "@opal/utils";
import { type Packet, StopReason } from "@/app/app/services/streamingModels";
import { constructCurrentMemoryState } from "@/lib/timeline/chat/renderers/memory/memoryStateUtils";
import { isMemoryToolPackets } from "@/lib/timeline/chat/packetHelpers";
import { MemoryTagWithTooltip } from "@/lib/timeline/components/headers/MemoryTagWithTooltip";
import { FullChatState } from "@/lib/timeline/chat/message/messageComponents/types";
import {
  TurnGroup,
  TransformedStep,
  toChatTimelineEntry,
} from "@/lib/timeline/chat/transformers";
import { useTimelineHeader } from "@/lib/timeline/chat/hooks/useTimelineHeader";
import { useTimelineStepState } from "@/lib/timeline/chat/hooks/useTimelineStepState";
import { useStreamingStartTime } from "@/app/app/stores/useChatSessionStore";
import { RunCard } from "@/lib/timeline/components/RunCard";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { ChatStep } from "@/lib/timeline/chat/ChatStep";
import type { TimelineEntryStatus } from "@/lib/timeline/types";
import type { AwaitingUser } from "@/lib/chat/toolApprovals";

/**
 * A run with at most this many steps shows each step as a hoisted run card
 * (one step each); a run with more is one collapsed run card. Change it here.
 */
export const MAX_HOISTED_STEPS = 5;

/** How long the hoisted step cards take to fold into the run card, in ms. */
const HANDOVER_MS = 300;

/** hoisted → handover → collapsed; a run never goes back. */
type RunLayout = "hoisted" | "handover" | "collapsed";

export interface AgentTimelineProps {
  /** Turn groups from usePacketProcessor */
  turnGroups: TurnGroup[];
  /** Chat state for rendering content */
  chatState: FullChatState;
  /** Whether the stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping (if stopped) */
  stopReason?: StopReason;
  /** Whether final answer is coming (affects last connector) */
  finalAnswerComing?: boolean;
  /** Whether there is display content after timeline */
  hasDisplayContent?: boolean;
  /** Processing duration in seconds (for completed messages) */
  processingDurationSeconds?: number;
  /** Tool processing duration from backend (via MESSAGE_START packet) */
  toolProcessingDuration?: number;
  /** A code mode program works between tool calls; it has no step */
  codeModeWorking?: boolean;
  /** A tool call in the latest turn waits for the user's approval or
   * answers */
  awaitingUser?: AwaitingUser | null;
  /** The run is the response's first, so the response's start and duration
   * time it. A later run times itself while it works here. */
  isFirstRun?: boolean;
}

/**
 * Custom prop comparison for AgentTimeline memoization.
 * Prevents unnecessary re-renders when parent renders but props haven't meaningfully changed.
 */
function areAgentTimelinePropsEqual(
  prev: AgentTimelineProps,
  next: AgentTimelineProps
): boolean {
  return (
    prev.turnGroups === next.turnGroups &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.finalAnswerComing === next.finalAnswerComing &&
    prev.hasDisplayContent === next.hasDisplayContent &&
    prev.processingDurationSeconds === next.processingDurationSeconds &&
    prev.chatState === next.chatState &&
    prev.toolProcessingDuration === next.toolProcessingDuration &&
    prev.codeModeWorking === next.codeModeWorking &&
    prev.awaitingUser === next.awaitingUser &&
    prev.isFirstRun === next.isFirstRun
  );
}

interface ChatRunStep {
  id: string;
  status: TimelineEntryStatus;
  step: TransformedStep;
}

/**
 * A step's status for the run card. A step that never closed counts as done
 * once the stream ends, or as stopped when the user stopped it.
 */
function runStatus(
  step: TransformedStep,
  stopPacketSeen: boolean,
  userStopped: boolean
): TimelineEntryStatus {
  const status = toChatTimelineEntry(step).status;
  if (status !== "streaming" || !stopPacketSeen) return status;
  return userStopped ? "stopped" : "done";
}

/** A memory step's tag, from the step's own packets. */
function memoryStepTag(packets: Packet[]): React.ReactNode {
  if (!isMemoryToolPackets(packets)) return undefined;
  const memory = constructCurrentMemoryState(packets);
  if (memory.operation === null) return undefined;
  return (
    <MemoryTagWithTooltip
      memoryText={memory.memoryText}
      memoryOperation={memory.operation}
      memoryId={memory.memoryId}
      memoryIndex={memory.index}
    />
  );
}

/** One run of a chat response's steps, on the shared run card. */
export const AgentTimeline = React.memo(function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  hasDisplayContent = false,
  processingDurationSeconds,
  toolProcessingDuration,
  codeModeWorking = false,
  awaitingUser = null,
  isFirstRun = true,
}: AgentTimelineProps) {
  const { headerText, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    codeModeWorking,
    awaitingUser
  );
  const { memoryText, memoryOperation, memoryId, memoryIndex } =
    useTimelineStepState(turnGroups);
  const streamingStartTime = useStreamingStartTime();

  const steps = useMemo<ChatRunStep[]>(
    () =>
      turnGroups
        .flatMap((group) => group.steps)
        .map((step) => ({
          id: step.key,
          status: runStatus(step, stopPacketSeen, userStopped),
          step,
        })),
    [turnGroups, stopPacketSeen, userStopped]
  );
  // The run works until the stream ends or text follows it; a wait for an
  // approval or an answer keeps it working after text.
  const isActive =
    !stopPacketSeen && (!hasDisplayContent || awaitingUser !== null);

  // Hoisted: each step of a short run is its own run card, with the step's
  // title as its header. Once the run has more steps, they collapse into one
  // run card: the step cards fold together into its place as it fades in,
  // folded.
  const hoisted = steps.length > 0 && steps.length <= MAX_HOISTED_STEPS;
  const [layout, setLayout] = useState<RunLayout>(
    hoisted ? "hoisted" : "collapsed"
  );
  // Whether the run card took the step cards' place here: it then fades in,
  // folded.
  const [cardHandedOver, setCardHandedOver] = useState(false);
  if (hoisted && layout === "collapsed") setLayout("hoisted");
  if (!hoisted && layout === "hoisted") {
    setLayout(prefersReducedMotion() ? "collapsed" : "handover");
    setCardHandedOver(true);
  }

  const boxRef = useRef<HTMLDivElement>(null);
  const stepsRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (layout !== "handover") return;
    const box = boxRef.current;
    const stepList = stepsRef.current;
    const card = cardRef.current;
    if (!box || !stepList || !card) {
      setLayout("collapsed");
      return;
    }
    // Focus inside the outgoing step cards moves to the run card's fold
    // control; the step cards are inert while they leave.
    if (stepList.contains(document.activeElement)) {
      card.querySelector<HTMLElement>("button")?.focus();
    }
    // The box closes from the step cards' height to the run card's, while
    // each step card slides up into the first one's place and fades.
    const ease = `${HANDOVER_MS}ms ease-in-out`;
    box.style.height = `${stepList.offsetHeight}px`;
    const items = Array.from(
      stepList.querySelectorAll<HTMLElement>("[data-run-handover-step]")
    );
    const top = items[0]?.offsetTop ?? 0;
    const offsets = items.map((item) => item.offsetTop - top);
    void box.offsetHeight;
    box.style.transition = `height ${ease}`;
    box.style.height = `${card.offsetHeight}px`;
    // Shrink toward the top inline-start corner, so the icons keep their
    // column.
    const origin =
      getComputedStyle(box).direction === "rtl" ? "top right" : "top left";
    items.forEach((item, index) => {
      item.style.transformOrigin = origin;
      item.style.transition = `transform ${ease}, opacity ${ease}`;
      item.style.transform = `translateY(${-(offsets[index] ?? 0)}px) scale(0.96)`;
      item.style.opacity = "0";
    });
    const done = window.setTimeout(() => {
      box.style.height = "";
      box.style.transition = "";
      setLayout("collapsed");
    }, HANDOVER_MS);
    return () => window.clearTimeout(done);
  }, [layout]);

  const stepCards = (
    <TimelineRoot>
      <Section alignItems="stretch" gap={2} height="auto">
        {steps.slice(0, MAX_HOISTED_STEPS).map((runStep) => (
          // A step that arrives while the run works rises in; a saved run's
          // steps appear at once.
          <Presence
            key={runStep.id}
            appear={isActive}
            grow
            data-run-handover-step=""
          >
            <ChatStep
              step={runStep.step}
              status={runStep.status}
              position={{ isFirst: true, isLast: true }}
              chatState={chatState}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
              // A finished memory step keeps its tag in its header, as the
              // collapsed run card does.
              headerAccessory={
                runStep.status === "done"
                  ? memoryStepTag(runStep.step.packets)
                  : undefined
              }
            />
          </Presence>
        ))}
        {/* A short run has no run card of its own, so a wait for the user's
            approval or answer shows as a header-only card under its steps. */}
        <Presence show={awaitingUser !== null} grow>
          <RunCard
            steps={[]}
            workingText={headerText}
            isActive
            renderStep={() => null}
          />
        </Presence>
      </Section>
    </TimelineRoot>
  );

  return (
    // The step cards and the run card share one box, so the step cards keep
    // their state into the handover and the run card stays mounted after it.
    <div ref={boxRef} className="relative">
      {layout !== "hoisted" && (
        <div key="card" ref={cardRef}>
          <Presence appear={cardHandedOver}>
            {/* Collapsed: the run's steps in one run card, titled by its
                current step while it works. */}
            <RunCard
              steps={steps}
              workingText={headerText}
              icon={SvgListTree}
              appear={!cardHandedOver}
              startFolded={cardHandedOver}
              isActive={isActive}
              // A stop after text followed did not end this run's work.
              isStopped={stopPacketSeen && userStopped && !hasDisplayContent}
              autoCollapse={hasDisplayContent}
              streamingStartTime={isFirstRun ? streamingStartTime : undefined}
              durationSeconds={
                isFirstRun
                  ? (toolProcessingDuration ?? processingDurationSeconds)
                  : undefined
              }
              summary={{
                memoryText,
                memoryOperation,
                memoryId,
                memoryIndex,
              }}
              renderStep={(runStep, position) => (
                <ChatStep
                  step={runStep.step}
                  status={runStep.status}
                  position={position}
                  chatState={chatState}
                  stopPacketSeen={stopPacketSeen}
                  stopReason={stopReason}
                />
              )}
            />
          </Presence>
        </div>
      )}
      {layout !== "collapsed" && (
        <div
          key="steps"
          ref={stepsRef}
          // During the handover the step cards lie over the run card.
          className={
            layout === "handover"
              ? "absolute inset-x-0 top-0 pointer-events-none"
              : undefined
          }
          aria-hidden={layout === "handover" || undefined}
          inert={layout === "handover" || undefined}
        >
          {stepCards}
        </div>
      )}
    </div>
  );
}, areAgentTimelinePropsEqual);

export default AgentTimeline;
