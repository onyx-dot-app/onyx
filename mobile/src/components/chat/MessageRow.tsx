// Memoized on packet count, not array identity: a row re-renders only when its own packets grow.
import { Fragment, memo, useMemo, useState } from "react";
import { View } from "react-native";

import { selectSources } from "@/chat/citations";
import { Message } from "@/chat/interfaces";
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
import { usePacketDisplay } from "@/hooks/usePacketDisplay";

// The renderer's onComplete drives the timeline pacing gate (9b.7); nothing consumes it in PR4.
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
  const { packets, processed, hasDisplayContent } = usePacketDisplay(node);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  // Which step's text the full-text reader is showing. Owned here, not in the step: the timeline
  // auto-collapses when the answer starts, which would unmount the step mid-read.
  const [fullTextKey, setFullTextKey] = useState<string | null>(null);
  const hasContent = hasDisplayContent && packets.length > 0;

  // Re-derived every flush so the reader stays live while the step streams on — parking the string
  // at open time would freeze the body and make Copy yield a truncated prefix. Reasoning is the only
  // renderer using the reader today; other long-form steps would resolve their own group here.
  const fullText = useMemo(
    () => resolveGroupReasoning(processed.groupedPacketsMap, fullTextKey),
    [fullTextKey, processed],
  );

  // Only after the answer completes, to avoid mid-stream layout shift.
  const sources = useMemo(
    () => (processed.isComplete ? selectSources(processed) : null),
    [processed],
  );

  // Context a renderer may read. This identity churns each flush, but RendererComponent's memo keys on
  // agent.id, not this object, so that's harmless.
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

  // Web AgentMessage: the timeline (above) owns the loader; answer and sources sit below.
  return (
    <View className="gap-12 py-6">
      <AgentTimeline
        agent={agent}
        isLoading={!hasContent && !processed.isComplete}
      />
      {hasContent ? (
        // px-12 aligns the answer under the avatar rail (web's px-3).
        <View className="px-12">
          <RendererComponent
            packets={packets}
            chatState={chatState}
            messageNodeId={node.nodeId}
            onComplete={NOOP}
            animate={!processed.isComplete}
            stopPacketSeen={processed.stopPacketSeen}
            stopReason={processed.stopReason}
          >
            {(results) => (
              <>
                {results.map((result, index) => (
                  <Fragment key={index}>{result.content}</Fragment>
                ))}
              </>
            )}
          </RendererComponent>
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
    prev.node.packets.length === next.node.packets.length &&
    prev.node.files === next.node.files &&
    prev.agent === next.agent,
);
