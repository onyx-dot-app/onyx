// Memoized on packetCount (not array identity): a row re-renders only when its own packets grow, so
// streaming one message doesn't re-render the list.
import { memo } from "react";
import { View } from "react-native";

import { Message } from "@/chat/interfaces";
import { Text } from "@/components/ui/text";
import { usePacketDisplay } from "@/hooks/usePacketDisplay";

function UserMessage({ message }: { message: string }) {
  return (
    <View className="items-end py-6">
      <View className="max-w-[85%] rounded-16 bg-background-tint-02 px-16 py-12">
        <Text font="main-content-body" color="text-05">
          {message}
        </Text>
      </View>
    </View>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <View className="py-6">
      <Text font="main-content-body" color="status-error-05">
        {message || "Something went wrong. Please try again."}
      </Text>
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
  if (node.type === "user") return <UserMessage message={node.message} />;
  if (node.type === "error") return <ErrorMessage message={node.message} />;
  return <AssistantMessage node={node} />;
}

export const MessageRow = memo(
  MessageRowComponent,
  (prev, next) =>
    prev.node.nodeId === next.node.nodeId &&
    prev.node.type === next.node.type &&
    prev.node.message === next.node.message &&
    prev.node.messageId === next.node.messageId &&
    prev.node.packets.length === next.node.packets.length,
);
