import { ActivityIndicator, View } from "react-native";

import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { Card } from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Text } from "@/components/ui/text";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";
import { timeAgo } from "@/lib/time";
import SvgBubbleText from "@/icons/bubble-text";
import type { MinimalAgent } from "@/chat/agents";
import type { ChatSessionSummary } from "@/api/chat/sessions";

interface ProjectChatSessionListProps {
  chats: ChatSessionSummary[];
  agents?: MinimalAgent[];
  personaIdToFeatured?: Record<number, boolean>;
  isLoading?: boolean;
  onSelect: (sessionId: string) => void;
}

// The project's chats, newest first; read-only in PR 6 (no move/remove/delete).
export function ProjectChatSessionList({
  chats,
  agents = [],
  personaIdToFeatured = {},
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
          // agent avatar only for a non-featured custom agent; else a bubble
          const personaId = chat.persona_id;
          const isFeatured =
            personaId != null ? personaIdToFeatured[personaId] : undefined;
          const agent =
            isFeatured === false && personaId != null
              ? agents.find((a) => a.id === personaId)
              : undefined;
          return (
            <LineItemButton
              key={chat.id}
              sizePreset="main-ui"
              variant="section"
              leading={
                agent ? (
                  <AgentAvatar agent={agent} size={18} />
                ) : (
                  <Icon as={SvgBubbleText} size={18} className="text-text-02" />
                )
              }
              title={chat.name && chat.name.trim() ? chat.name : UNNAMED_CHAT}
              description={updated ? `Last message ${updated}` : undefined}
              onPress={() => onSelect(chat.id)}
            />
          );
        })
      )}
    </View>
  );
}
