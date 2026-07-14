// Memoized on packetCount (not array identity): a row re-renders only when its own packets grow, so
// streaming one message doesn't re-render the list.
import { memo } from "react";
import { View } from "react-native";

import { Message } from "@/chat/interfaces";
import { getErrorTitle } from "@/chat/errorHelpers";
import { fileDescriptorToDisplayFile } from "@/chat/fileDescriptors";
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
        // Web parity (HumanMessage): tint bubble, px-3/py-2, asymmetric corners (square bottom-right).
        <View className="max-w-[85%] rounded-t-16 rounded-bl-16 bg-background-tint-02 px-12 py-8">
          <Text font="main-content-body" color="text-05">
            {node.message}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

// Web parity: the ErrorBanner (red Alert "broken" box) — code-derived title + the raw error text.
// Mobile port shows one alert icon (web varies it by code) and no stack-trace/regenerate yet.
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

function AssistantMessage({ node }: { node: Message }) {
  const { renderer, packets, isComplete } = usePacketDisplay(node);
  const Renderer = renderer?.Component;

  return (
    <View className="py-6">
      {Renderer && packets.length > 0 ? (
        <Renderer packets={packets} isComplete={isComplete} />
      ) : (
        // no content yet — thinking placeholder
        <Text font="main-content-muted" color="text-03">
          …
        </Text>
      )}
    </View>
  );
}

function MessageRowComponent({ node }: { node: Message }) {
  if (node.type === "user") return <UserMessage node={node} />;
  if (node.type === "error") return <ErrorMessage node={node} />;
  return <AssistantMessage node={node} />;
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
    // user rows render attachment chips from node.files; re-render if that array is replaced
    prev.node.files === next.node.files,
);
