"use client";

import { useState, useCallback, useMemo } from "react";
import { Packet } from "@/app/app/services/streamingModels";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { FeedbackType, Message } from "@/app/app/interfaces";
import { LlmManager } from "@/lib/hooks";
import { RegenerationFactory } from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelPanel from "@/app/app/message/MultiModelPanel";
import { cn } from "@/lib/utils";

export interface MultiModelResponse {
  modelIndex: number;
  provider: string;
  modelName: string;
  displayName: string;
  packets: Packet[];
  packetCount: number;
  nodeId: number;
  messageId?: number;
  isHighlighted?: boolean;
  currentFeedback?: FeedbackType | null;
  isGenerating?: boolean;
}

export interface MultiModelResponseViewProps {
  responses: MultiModelResponse[];
  chatState: FullChatState;
  llmManager: LlmManager | null;
  onRegenerate?: RegenerationFactory;
  parentMessage?: Message | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
}

export default function MultiModelResponseView({
  responses,
  chatState,
  llmManager,
  onRegenerate,
  parentMessage,
  otherMessagesCanSwitchTo,
  onMessageSelection,
}: MultiModelResponseViewProps) {
  const [preferredIndex, setPreferredIndex] = useState<number | null>(null);
  const [hiddenPanels, setHiddenPanels] = useState<Set<number>>(new Set());

  const isGenerating = useMemo(
    () => responses.some((r) => r.isGenerating),
    [responses]
  );

  const visibleResponses = useMemo(
    () => responses.filter((r) => !hiddenPanels.has(r.modelIndex)),
    [responses, hiddenPanels]
  );

  const hiddenResponses = useMemo(
    () => responses.filter((r) => hiddenPanels.has(r.modelIndex)),
    [responses, hiddenPanels]
  );

  const toggleVisibility = useCallback(
    (modelIndex: number) => {
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        if (next.has(modelIndex)) {
          next.delete(modelIndex);
        } else {
          // Don't hide the last visible panel
          const visibleCount = responses.length - next.size;
          if (visibleCount <= 1) return prev;
          next.add(modelIndex);
        }
        return next;
      });
    },
    [responses.length]
  );

  const handleSelectPreferred = useCallback(
    (modelIndex: number) => {
      setPreferredIndex(modelIndex);
      const response = responses[modelIndex];
      if (!response) return;
      // Sync with message tree — mark this response as the latest child
      // so the next message chains from it.
      if (onMessageSelection) {
        onMessageSelection(response.nodeId);
      }
    },
    [responses, onMessageSelection]
  );

  // Selection mode when preferred is set and not generating
  const showSelectionMode =
    preferredIndex !== null && !isGenerating && visibleResponses.length > 1;

  // Build common panel props
  const buildPanelProps = useCallback(
    (response: MultiModelResponse, isNonPreferred: boolean) => ({
      modelIndex: response.modelIndex,
      provider: response.provider,
      modelName: response.modelName,
      displayName: response.displayName,
      isPreferred: preferredIndex === response.modelIndex,
      isHidden: false as const,
      isNonPreferredInSelection: isNonPreferred,
      onSelect: () => handleSelectPreferred(response.modelIndex),
      onToggleVisibility: () => toggleVisibility(response.modelIndex),
      agentMessageProps: {
        rawPackets: response.packets,
        packetCount: response.packetCount,
        chatState,
        nodeId: response.nodeId,
        messageId: response.messageId,
        currentFeedback: response.currentFeedback,
        llmManager,
        otherMessagesCanSwitchTo,
        onMessageSelection,
        onRegenerate,
        parentMessage,
      },
    }),
    [
      preferredIndex,
      handleSelectPreferred,
      toggleVisibility,
      chatState,
      llmManager,
      otherMessagesCanSwitchTo,
      onMessageSelection,
      onRegenerate,
      parentMessage,
    ]
  );

  // Shared renderer for hidden panels (inline in the flex row)
  const renderHiddenPanels = () =>
    hiddenResponses.map((r) => (
      <div key={r.modelIndex} className="w-[240px] shrink-0">
        <MultiModelPanel
          modelIndex={r.modelIndex}
          provider={r.provider}
          modelName={r.modelName}
          displayName={r.displayName}
          isPreferred={false}
          isHidden
          isNonPreferredInSelection={false}
          onSelect={() => handleSelectPreferred(r.modelIndex)}
          onToggleVisibility={() => toggleVisibility(r.modelIndex)}
          agentMessageProps={buildPanelProps(r, false).agentMessageProps}
        />
      </div>
    ));

  if (showSelectionMode) {
    // ── Selection Layout ──
    // Preferred stays at normal chat width, centered.
    // Non-preferred panels are pushed to the viewport edges and clip off-screen.
    const preferredIdx = visibleResponses.findIndex(
      (r) => r.modelIndex === preferredIndex
    );
    const preferred = visibleResponses[preferredIdx];
    const leftPanels = visibleResponses.slice(0, preferredIdx);
    const rightPanels = visibleResponses.slice(preferredIdx + 1);

    // Non-preferred panel width and gap between panels
    const PANEL_W = 400;
    const GAP = 16;

    return (
      <div className="w-full relative overflow-hidden">
        {/* Preferred — centered at normal chat width, in flow to set container height */}
        {preferred && (
          <div className="w-full max-w-[720px] min-w-[400px] mx-auto">
            <MultiModelPanel {...buildPanelProps(preferred, false)} />
          </div>
        )}

        {/* Non-preferred on the left — anchored to the left of the preferred panel */}
        {leftPanels.map((r, i) => (
          <div
            key={r.modelIndex}
            className="absolute top-0"
            style={{
              width: `${PANEL_W}px`,
              // Right edge of this panel sits just left of the preferred panel
              right: `calc(50% + var(--app-page-main-content-width) / 2 + ${
                GAP + i * (PANEL_W + GAP)
              }px)`,
            }}
          >
            <MultiModelPanel {...buildPanelProps(r, true)} />
          </div>
        ))}

        {/* Non-preferred on the right — anchored to the right of the preferred panel */}
        {rightPanels.map((r, i) => (
          <div
            key={r.modelIndex}
            className="absolute top-0"
            style={{
              width: `${PANEL_W}px`,
              // Left edge of this panel sits just right of the preferred panel
              left: `calc(50% + var(--app-page-main-content-width) / 2 + ${
                GAP + i * (PANEL_W + GAP)
              }px)`,
            }}
          >
            <MultiModelPanel {...buildPanelProps(r, true)} />
          </div>
        ))}
      </div>
    );
  }

  // ── Generation Layout (equal panels) ──
  return (
    <div className="flex gap-6 items-start justify-center">
      {visibleResponses.map((r) => (
        <div key={r.modelIndex} className="flex-1 min-w-[400px] max-w-[720px]">
          <MultiModelPanel {...buildPanelProps(r, false)} />
        </div>
      ))}
      {renderHiddenPanels()}
    </div>
  );
}
