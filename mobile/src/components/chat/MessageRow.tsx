// Memoized on packet count, not array identity: a row re-renders only when its own packets grow.
import { Fragment, memo, useMemo, useState } from "react";
import { View } from "react-native";

import { selectSources } from "@/chat/citations";
import { Message } from "@/chat/interfaces";
import { StopReason } from "@/chat/streamingModels";
import { resolveGroupReasoning } from "@/chat/timeline/reasoningState";
import { MinimalAgent } from "@/chat/agents";
import { getErrorTitle } from "@/chat/errorHelpers";
import { fileDescriptorToDisplayFile } from "@/chat/fileDescriptors";
import { openSource } from "@/chat/openSource";
import { AgentTimeline } from "@/components/chat/AgentTimeline";
import {
  CitedSourcesBar,
  CitedSourcesSheet,
} from "@/components/chat/CitedSources";
import { FileCard } from "@/components/chat/FileCard";
import { RendererComponent } from "@/components/chat/renderers/RendererComponent";
import type { FullChatState } from "@/components/chat/renderers/registry";
import { ReasoningTextSheet } from "@/components/chat/timeline/ReasoningTextSheet";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgAlertCircle from "@/icons/alert-circle";
import { usePacedTurnGroups } from "@/hooks/timeline/usePacedTurnGroups";
import { usePacketProcessor } from "@/hooks/timeline/usePacketProcessor";

// Non-final display groups don't complete the message.
const NOOP = (): void => {};

function UserMessage({ node }: { node: Message }) {
  const files = node.files.map(fileDescriptorToDisplayFile);
  return (
    <View className="items-end py-6">
      {files.length > 0 ? (
        <View className="mb-8 max-w-[85%] flex-row flex-wrap justify-end gap-8">
          {files.map((file) => (
            <FileCard key={file.id} file={file} />
          ))}
        </View>
      ) : null}
      {node.message.length > 0 ? (
        // Web HumanMessage bubble: squared bottom-right corner.
        <View className="max-w-[85%] rounded-t-16 rounded-bl-16 bg-background-tint-02 px-12 py-8">
          {/* 14px body: deliberate reduction from web's 16px, which reads oversized on a phone. */}
          <Text font="main-ui-body" color="text-05">
            {node.message}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

// Web ErrorBanner. No regenerate action yet.
function ErrorMessage({ node }: { node: Message }) {
  return (
    <View className="py-6">
      <View className="flex-row gap-8 rounded-12 border border-status-error-05 bg-status-error-01 px-12 py-12">
        <Icon
          as={SvgAlertCircle}
          size={16}
          className="mt-2 text-status-error-05"
        />
        <View className="flex-1 gap-4">
          <Text font="main-ui-action" color="status-error-05">
            {getErrorTitle(node.errorCode)}
          </Text>
          <Text font="main-ui-body" color="status-error-05">
            {node.message || "An error occurred. Please try again."}
          </Text>
        </View>
      </View>
    </View>
  );
}

function AssistantMessage({
  node,
  agent,
}: {
  node: Message;
  agent: MinimalAgent | null;
}) {
  const {
    processed,
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
  } = usePacketProcessor(node.packets, node.nodeId);

  // Withholds the answer until every step has been revealed.
  const { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing } =
    usePacedTurnGroups(
      toolTurnGroups,
      displayGroups,
      stopPacketSeen,
      node.nodeId,
      finalAnswerComing,
    );

  const [sourcesOpen, setSourcesOpen] = useState(false);
  // Which step's text the full-text reader is showing. Owned here, not in the step: the timeline
  // auto-collapses when the answer starts, which would unmount the step mid-read.
  const [fullTextKey, setFullTextKey] = useState<string | null>(null);
  const hasDisplayContent = pacedDisplayGroups.length > 0;

  // Re-derived every flush so the reader keeps up with a step that is still streaming; parking the
  // string at open time would freeze the body and make Copy yield a truncated prefix.
  const fullText = useMemo(
    () => resolveGroupReasoning(processed.groupedPacketsMap, fullTextKey),
    [fullTextKey, processed],
  );

  // Only after the answer completes, to avoid mid-stream layout shift.
  const sources = useMemo(
    () => (processed.isComplete ? selectSources(processed) : null),
    [processed],
  );

  // Keyed on the maps, not on web's `citations.length` proxy: web gets away with a count because it
  // mutates one map in place, but mobile rebuilds state each flush, so a count would pin a stale map
  // and a re-cited document would resolve against old metadata.
  const chatState = useMemo<FullChatState>(
    () => ({
      agent,
      citations: processed.citationMap,
      documentMap: processed.documentMap,
      openSource,
      openFullText: setFullTextKey,
    }),
    [agent, processed.citationMap, processed.documentMap],
  );

  // The timeline owns the loading state, so there's no separate spinner here.
  return (
    <View className="gap-12 py-6">
      <AgentTimeline
        turnGroups={pacedTurnGroups}
        chatState={chatState}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
        hasDisplayContent={hasDisplayContent}
        finalAnswerComing={pacedFinalAnswerComing}
        processingDurationSeconds={node.processingDurationSeconds ?? undefined}
        isGeneratingImage={isGeneratingImage}
        generatedImageCount={generatedImageCount}
        toolProcessingDuration={toolProcessingDuration}
        streamingStartTime={node.streamingStartedAt}
      />
      {hasDisplayContent ? (
        // px-12 aligns the answer under the avatar rail (web's px-3).
        <View className="gap-12 px-12">
          {pacedDisplayGroups.map((displayGroup, groupIndex) => (
            <RendererComponent
              key={`${displayGroup.turn_index}-${displayGroup.tab_index}`}
              packets={displayGroup.packets}
              chatState={chatState}
              messageNodeId={node.nodeId}
              hasTimelineThinking={pacedTurnGroups.length > 0 || hasSteps}
              // Only the last group completes the message.
              onComplete={
                groupIndex === pacedDisplayGroups.length - 1
                  ? onRenderComplete
                  : NOOP
              }
              animate={!stopPacketSeen}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
            >
              {(results) => (
                <>
                  {results.map((result, index) => (
                    <Fragment key={index}>{result.content}</Fragment>
                  ))}
                </>
              )}
            </RendererComponent>
          ))}
        </View>
      ) : stopReason === StopReason.USER_CANCELLED ? (
        <View className="px-12">
          <Text font="secondary-body" color="text-04">
            User has stopped generation
          </Text>
        </View>
      ) : null}
      {sources && sources.hasSources ? (
        <View className="px-12">
          <CitedSourcesBar
            iconDocs={sources.iconDocs}
            count={sources.count}
            onPress={() => setSourcesOpen(true)}
          />
          <CitedSourcesSheet
            visible={sourcesOpen}
            onClose={() => setSourcesOpen(false)}
            sources={sources}
          />
        </View>
      ) : null}
      {fullText !== null ? (
        <ReasoningTextSheet
          visible
          onClose={() => setFullTextKey(null)}
          content={fullText}
        />
      ) : null}
    </View>
  );
}

function MessageRowComponent({
  node,
  agent,
}: {
  node: Message;
  agent: MinimalAgent | null;
}) {
  if (node.type === "user") return <UserMessage node={node} />;
  if (node.type === "error") return <ErrorMessage node={node} />;
  return <AssistantMessage node={node} agent={agent} />;
}

export const MessageRow = memo(
  MessageRowComponent,
  (prev, next) =>
    prev.node.nodeId === next.node.nodeId &&
    prev.node.type === next.node.type &&
    prev.node.message === next.node.message &&
    prev.node.messageId === next.node.messageId &&
    prev.node.errorCode === next.node.errorCode &&
    prev.node.streamingStartedAt === next.node.streamingStartedAt &&
    prev.node.processingDurationSeconds ===
      next.node.processingDurationSeconds &&
    prev.node.packets.length === next.node.packets.length &&
    prev.node.files === next.node.files &&
    prev.agent === next.agent,
);
