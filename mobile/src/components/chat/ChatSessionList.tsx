import { View } from "react-native";

import { Text } from "@/components/ui/text";
// Direct import (not the barrel) keeps this clear of the sidebar overlay's
// reanimated dependency, so it stays unit-testable under jest.
import { SidebarTab } from "@/components/sidebar/SidebarTab";
import SvgBubbleText from "@/icons/bubble-text";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// Web's UNNAMED_CHAT fallback for not-yet-named sessions.
export const UNNAMED_CHAT = "New Chat";

interface ChatSessionListProps {
  sessions: ChatSessionSummary[];
  currentSessionId?: string | null;
  isLoading?: boolean;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  onSelect: (sessionId: string) => void;
  onLoadMore?: () => void;
}

// Flat "Recents" list (mirrors web's RecentsSection); presentational so it
// unit-tests standalone.
export function ChatSessionList({
  sessions,
  currentSessionId,
  isLoading = false,
  hasMore = false,
  isLoadingMore = false,
  onSelect,
  onLoadMore,
}: ChatSessionListProps) {
  if (!isLoading && sessions.length === 0) {
    return (
      <View className="px-2 py-2">
        <Text font="secondary-body" color="text-03">
          Try sending a message! Your chat history will appear here.
        </Text>
      </View>
    );
  }

  return (
    <>
      {sessions.map((session) => (
        <SidebarTab
          key={session.id}
          icon={SvgBubbleText}
          selected={session.id === currentSessionId}
          onPress={() => onSelect(session.id)}
        >
          {session.name && session.name.trim() ? session.name : UNNAMED_CHAT}
        </SidebarTab>
      ))}
      {hasMore ? (
        <SidebarTab
          variant="sidebar-light"
          disabled={isLoadingMore}
          onPress={onLoadMore}
        >
          {isLoadingMore ? "Loading…" : "Show older chats"}
        </SidebarTab>
      ) : null}
    </>
  );
}
