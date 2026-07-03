import { ActivityIndicator, Pressable, View } from "react-native";

import { Card } from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";
import { timeAgo } from "@/lib/time";
import SvgBubbleText from "@/icons/bubble-text";
import type { ChatSessionSummary } from "@/api/chat/sessions";

interface ProjectChatSessionListProps {
  chats: ChatSessionSummary[];
  isLoading?: boolean;
  onSelect: (sessionId: string) => void;
}

// The project's chats, newest first; read-only in PR 6 (no move/remove/delete).
export function ProjectChatSessionList({
  chats,
  isLoading = false,
  onSelect,
}: ProjectChatSessionListProps) {
  const sorted = [...chats].sort(
    (a, b) =>
      new Date(b.time_updated).getTime() - new Date(a.time_updated).getTime(),
  );

  return (
    <View className="gap-8">
      <Text font="secondary-body" color="text-02">
        Recent Chats
      </Text>

      {isLoading && sorted.length === 0 ? (
        <ActivityIndicator size="small" />
      ) : sorted.length === 0 ? (
        <Card variant="tertiary">
          <Text font="secondary-body" color="text-02">
            No chats yet.
          </Text>
        </Card>
      ) : (
        sorted.map((chat) => {
          const updated = timeAgo(chat.time_updated);
          return (
            <Pressable
              key={chat.id}
              onPress={() => onSelect(chat.id)}
              className="flex-row items-center gap-8 rounded-12 px-8 py-8 active:bg-background-tint-03"
            >
              <Icon as={SvgBubbleText} size={18} className="text-text-02" />
              <View className="min-w-0 flex-1">
                <Text font="main-ui-body" color="text-04" numberOfLines={1}>
                  {chat.name && chat.name.trim() ? chat.name : UNNAMED_CHAT}
                </Text>
                {updated ? (
                  <Text font="secondary-body" color="text-03" numberOfLines={1}>
                    {`Last message ${updated}`}
                  </Text>
                ) : null}
              </View>
            </Pressable>
          );
        })
      )}
    </View>
  );
}
