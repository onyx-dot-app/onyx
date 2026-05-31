// AgentMessage.tsx — orchestrates a single assistant turn: runs the packet
// pipeline + pacing, renders the AgentTimeline (thinking/tools) then the final
// answer (markdown + citations). Ported from web AgentMessage (TTS / toolbar /
// message-switching dropped for this pass; seams left for them).

import { memo, useMemo, type ReactNode } from "react";
import { View } from "react-native";

import { StopReason, type Packet } from "@/lib/types";
import { Text } from "@/components/opal";
import type { FullChatState } from "@/components/message/interfaces";
import { usePacketProcessor } from "@/state/timeline/hooks/usePacketProcessor";
import { usePacedTurnGroups } from "@/state/timeline/hooks/usePacedTurnGroups";
import { AgentTimeline } from "@/components/message/timeline/AgentTimeline";
import { RendererComponent } from "@/components/message/renderMessageComponent";

export interface AgentMessageProps {
  rawPackets: Packet[];
  /** Separate primitive for memo comparison (history leaves it undefined). */
  packetCount?: number;
  chatState: FullChatState;
  nodeId: number;
  processingDurationSeconds?: number;
}

function arePropsEqual(prev: AgentMessageProps, next: AgentMessageProps): boolean {
  const prevCount = prev.packetCount ?? prev.rawPackets.length;
  const nextCount = next.packetCount ?? next.rawPackets.length;
  return (
    prev.nodeId === next.nodeId &&
    prevCount === nextCount &&
    prev.chatState.agent?.id === next.chatState.agent?.id &&
    prev.chatState.docs === next.chatState.docs &&
    prev.chatState.citations === next.chatState.citations &&
    prev.chatState.setPresentingDocument === next.chatState.setPresentingDocument &&
    prev.processingDurationSeconds === next.processingDurationSeconds
  );
}

export const AgentMessage = memo(function AgentMessage({
  rawPackets,
  chatState,
  nodeId,
  processingDurationSeconds,
}: AgentMessageProps) {
  const {
    citations,
    citationMap,
    documentMap,
    toolTurnGroups,
    displayGroups,
    hasSteps,
    stopPacketSeen,
    stopReason,
    isGeneratingImage,
    generatedImageCount,
    finalAnswerComing,
    toolProcessingDuration,
    onRenderComplete,
  } = usePacketProcessor(rawPackets, nodeId);

  const { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing } =
    usePacedTurnGroups(
      toolTurnGroups,
      displayGroups,
      stopPacketSeen,
      nodeId,
      finalAnswerComing
    );

  // citationMap / documentMap are mutated in place inside the processor ref, so
  // use citations.length / documentMap.size as cache-busting proxies.
  const mergedCitations = useMemo(
    () => ({ ...chatState.citations, ...citationMap }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chatState.citations, citationMap, citations.length]
  );
  const mergedDocs = useMemo(() => {
    const propDocs = chatState.docs ?? [];
    if (documentMap.size === 0) return propDocs;
    const seen = new Set(propDocs.map((d) => d.document_id));
    const extras = Array.from(documentMap.values()).filter(
      (d) => !seen.has(d.document_id)
    );
    return extras.length > 0 ? [...propDocs, ...extras] : propDocs;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatState.docs, documentMap, documentMap.size]);

  const effectiveChatState = useMemo<FullChatState>(
    () => ({ ...chatState, citations: mergedCitations, docs: mergedDocs }),
    // Intentionally granular deps (chatState is recreated upstream each render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      chatState.agent,
      chatState.setPresentingDocument,
      chatState.overriddenModel,
      chatState.researchType,
      mergedCitations,
      mergedDocs,
    ]
  );

  return (
    <View style={{ gap: 12 }}>
      <AgentTimeline
        turnGroups={pacedTurnGroups}
        chatState={effectiveChatState}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
        hasDisplayContent={pacedDisplayGroups.length > 0}
        processingDurationSeconds={processingDurationSeconds}
        isGeneratingImage={isGeneratingImage}
        generatedImageCount={generatedImageCount}
        finalAnswerComing={pacedFinalAnswerComing}
        toolProcessingDuration={toolProcessingDuration}
      />

      {pacedDisplayGroups.length > 0 && (
        <View style={{ paddingHorizontal: 12, gap: 12 }}>
          {pacedDisplayGroups.map((displayGroup, index) => (
            <RendererComponent
              key={`${displayGroup.turn_index}-${displayGroup.tab_index}`}
              packets={displayGroup.packets}
              chatState={effectiveChatState}
              messageNodeId={nodeId}
              hasTimelineThinking={pacedTurnGroups.length > 0 || hasSteps}
              onComplete={() => {
                if (index === pacedDisplayGroups.length - 1) onRenderComplete();
              }}
              animate={!stopPacketSeen}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
            >
              {(results): ReactNode => (
                <>
                  {results.map((r, i) => (
                    <View key={i}>{r.content}</View>
                  ))}
                </>
              )}
            </RendererComponent>
          ))}
        </View>
      )}

      {pacedDisplayGroups.length === 0 &&
        stopReason === StopReason.USER_CANCELLED && (
          <View style={{ paddingHorizontal: 12 }}>
            <Text font="secondary-body" color="text-04">
              User has stopped generation
            </Text>
          </View>
        )}
    </View>
  );
}, arePropsEqual);

export default AgentMessage;
