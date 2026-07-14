// Memoized on packet count, not array identity: a row re-renders only when its own packets grow.
import { memo } from "react";
import { View } from "react-native";

import { Message } from "@/chat/interfaces";
import { MinimalAgent } from "@/chat/agents";
import { getErrorTitle } from "@/chat/errorHelpers";
import { fileDescriptorToDisplayFile } from "@/chat/fileDescriptors";
import { AgentTimeline } from "@/components/chat/AgentTimeline";
import { FileCard } from "@/components/chat/FileCard";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgAlertCircle from "@/icons/alert-circle";
import { usePacketDisplay } from "@/hooks/usePacketDisplay";

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
        // Web parity: HumanMessage bubble with asymmetric corners (square bottom-right).
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

// Web parity: ErrorBanner — code-derived title + raw error. Single alert icon; no regenerate yet.
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
  const { renderer, packets, isComplete } = usePacketDisplay(node);
  const Renderer = renderer?.Component;
  const hasContent = Renderer != null && packets.length > 0;

  // Web AgentMessage: timeline (avatar + status) above the answer; the timeline owns the loader.
  return (
    <View className="gap-12 py-6">
      <AgentTimeline agent={agent} isLoading={!hasContent && !isComplete} />
      {hasContent ? (
        // Inset (px-12) aligns the answer under the avatar rail, matching web's px-3.
        <View className="px-12">
          <Renderer packets={packets} isComplete={isComplete} />
        </View>
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
    // user attachment chips: re-render if the files array is replaced
    prev.node.files === next.node.files &&
    // assistant avatar: re-render if the session's agent changes
    prev.agent === next.agent,
);
