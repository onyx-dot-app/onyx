import { useMemo } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/components/opal";
import { SvgBubbleText } from "@/components/icons";
import { useToken } from "@/theme/ThemeProvider";
import { formatRelativeTime } from "@/lib/projectUtils";
import { UNNAMED_CHAT } from "@/lib/chatLabels";
import type { ChatSession } from "@/lib/types";

// Native mirror of web `ProjectChatSessionList`: a "Recent Chats" header and the
// project's chat sessions (newest first), each a tappable row with name and a
// "Last message …" sub-line. Deviation: web shows an agent avatar for non-featured
// personas; mobile renders the bubble glyph for all.

interface ProjectChatSessionListProps {
  chats: ChatSession[];
  isLoading: boolean;
  onOpenChat: (chatSessionId: string) => void;
}

export function ProjectChatSessionList({
  chats,
  isLoading,
  onOpenChat,
}: ProjectChatSessionListProps) {
  const glyphColor = useToken("text-02");
  const skeletonColor = useToken("background-tint-03");

  const sorted = useMemo(
    () =>
      [...chats].sort(
        (a, b) =>
          new Date(b.time_updated).getTime() -
          new Date(a.time_updated).getTime(),
      ),
    [chats],
  );

  return (
    <View className="gap-2 px-4 pt-2">
      <View className="pl-1">
        <Text font="secondary-body" color="text-02">
          Recent Chats
        </Text>
      </View>

      {isLoading ? (
        <View className="gap-2">
          {(["70%", "55%", "62%"] as const).map((w, i) => (
            <View
              key={i}
              style={{
                width: w,
                height: 14,
                borderRadius: 7,
                backgroundColor: skeletonColor,
              }}
            />
          ))}
        </View>
      ) : sorted.length === 0 ? (
        <Text font="secondary-body" color="text-02" style={{ padding: 8 }}>
          No chats yet.
        </Text>
      ) : (
        <View className="gap-1">
          {sorted.map((chat) => (
            <Pressable
              key={chat.id}
              onPress={() => onOpenChat(chat.id)}
              accessibilityRole="button"
              accessibilityLabel={chat.name || UNNAMED_CHAT}
              className="flex-row gap-3 rounded-[8px] p-1.5 active:bg-background-tint-02"
            >
              <View className="pl-1 pt-1">
                <SvgBubbleText size={16} color={glyphColor} />
              </View>
              <View className="flex-1">
                <Text font="main-ui-body" color="text-03" numberOfLines={1}>
                  {chat.name || UNNAMED_CHAT}
                </Text>
                <Text font="secondary-body" color="text-03" numberOfLines={1}>
                  Last message {formatRelativeTime(chat.time_updated)}
                </Text>
              </View>
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}
