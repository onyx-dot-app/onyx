// Top-anchored FlashList mirroring web (short chats read top→down). Streaming auto-follow, the
// scroll-up-to-pause behavior, and the floating jump chevron all live in useChatAutoScroll; it honors
// the app-wide autoScroll setting.
import { useCallback, useRef } from "react";
import { Pressable, View } from "react-native";
import { FlashList, FlashListRef } from "@shopify/flash-list";

import { Message } from "@/chat/interfaces";
import { MinimalAgent } from "@/chat/agents";
import { contentSignature } from "@/chat/autoScroll";
import { MessageRow } from "@/components/chat/MessageRow";
import { Icon } from "@/components/ui/icon";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useSettings } from "@/state/settingsStore";
import SvgChevronDown from "@/icons/chevron-down";

interface MessageListProps {
  messages: Message[];
  // for the assistant-message avatar
  agent: MinimalAgent | null;
}

const FAB_SHADOW = {
  shadowColor: "#000000",
  shadowOffset: { width: 0, height: 2 },
  shadowOpacity: 0.12,
  shadowRadius: 8,
  elevation: 4,
} as const;

function keyExtractor(item: Message): string {
  return String(item.nodeId);
}

export function MessageList({ messages, agent }: MessageListProps) {
  const listRef = useRef<FlashListRef<Message>>(null);
  const autoScrollEnabled = useSettings((state) => state.autoScrollEnabled);
  const {
    onLoad,
    onLayout,
    onScroll,
    onScrollBeginDrag,
    onContentSizeChange,
    scrollToBottom,
    showScrollButton,
    maintainVisibleContentPosition,
  } = useChatAutoScroll(listRef, {
    enabled: autoScrollEnabled,
    contentSignature: contentSignature(messages),
  });

  const renderItem = useCallback(
    ({ item }: { item: Message }) => <MessageRow node={item} agent={agent} />,
    [agent],
  );

  return (
    <View className="flex-1" onLayout={onLayout}>
      <FlashList
        ref={listRef}
        data={messages}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        onLoad={onLoad}
        onScroll={onScroll}
        onScrollBeginDrag={onScrollBeginDrag}
        onContentSizeChange={onContentSizeChange}
        scrollEventThrottle={16}
        maintainVisibleContentPosition={maintainVisibleContentPosition}
        contentContainerStyle={{ paddingHorizontal: 16, paddingVertical: 8 }}
      />
      {showScrollButton ? (
        <View
          pointerEvents="box-none"
          className="absolute inset-x-0 bottom-16 items-center"
        >
          <Pressable
            onPress={scrollToBottom}
            accessibilityRole="button"
            accessibilityLabel="Scroll to bottom"
            style={FAB_SHADOW}
            className="h-36 w-36 items-center justify-center rounded-full border border-border-01 bg-background-neutral-00 active:bg-background-tint-02"
          >
            <Icon as={SvgChevronDown} size={20} className="text-text-03" />
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}
