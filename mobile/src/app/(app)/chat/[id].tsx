import { useLocalSearchParams } from "expo-router";

import { ChatConversation } from "@/components/chat/ChatConversation";

export default function ChatSessionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <ChatConversation sessionId={id} />;
}
