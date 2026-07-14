// Top-anchored FlashList mirroring web: short chats read top→down; MVCP autoscroll pins to the
// latest turn while streaming only when the user is near the bottom; a floating chevron returns
// after scrolling up.
import { useCallback, useRef, useState } from "react";
import {
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  View,
} from "react-native";
import { FlashList, FlashListRef } from "@shopify/flash-list";

import { Message } from "@/chat/interfaces";
import { MinimalAgent } from "@/chat/agents";
import { MessageRow } from "@/components/chat/MessageRow";
import { Icon } from "@/components/ui/icon";
import SvgChevronDown from "@/icons/chevron-down";

interface MessageListProps {
  messages: Message[];
  // for the assistant-message avatar
  agent: MinimalAgent | null;
}

// Newest turn this far below viewport → "scrolled up", reveal the button (web uses 32px).
const AT_BOTTOM_THRESHOLD_PX = 48;

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
  const didInitialScroll = useRef(false);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const renderItem = useCallback(
    ({ item }: { item: Message }) => <MessageRow node={item} agent={agent} />,
    [agent],
  );

  // Land on newest turn when opening a chat (web's session-load scroll-to-bottom); no-op for short
  // chats. Reset per session by keying this list on sessionId (see ChatSurface).
  const handleLoad = useCallback(() => {
    if (didInitialScroll.current) return;
    didInitialScroll.current = true;
    listRef.current?.scrollToEnd({ animated: false });
  }, []);

  const handleScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } =
        event.nativeEvent;
      const distanceFromBottom =
        contentSize.height - (contentOffset.y + layoutMeasurement.height);
      setShowScrollButton(distanceFromBottom > AT_BOTTOM_THRESHOLD_PX);
    },
    [],
  );

  const scrollToBottom = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: true });
  }, []);

  return (
    <View className="flex-1">
      <FlashList
        ref={listRef}
        data={messages}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        onLoad={handleLoad}
        onScroll={handleScroll}
        scrollEventThrottle={16}
        maintainVisibleContentPosition={{ autoscrollToBottomThreshold: 0.2 }}
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
