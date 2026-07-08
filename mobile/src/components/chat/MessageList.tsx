// FlashList v2 chat pattern: non-inverted + maintainVisibleContentPosition/startRenderingFromBottom keeps
// the view pinned to the bottom while streaming. Pagination lands in PR 4.
import { FlashList } from "@shopify/flash-list";

import { Message } from "@/chat/interfaces";
import { MessageRow } from "@/components/chat/MessageRow";

interface MessageListProps {
  messages: Message[];
}

function renderItem({ item }: { item: Message }) {
  return <MessageRow node={item} />;
}

function keyExtractor(item: Message): string {
  return String(item.nodeId);
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <FlashList
      data={messages}
      renderItem={renderItem}
      keyExtractor={keyExtractor}
      maintainVisibleContentPosition={{
        startRenderingFromBottom: true,
        autoscrollToBottomThreshold: 0.2,
      }}
      contentContainerStyle={{ paddingHorizontal: 16, paddingVertical: 8 }}
    />
  );
}
