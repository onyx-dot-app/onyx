import { ChatConversation } from "@/components/chat/ChatConversation";

// New-chat landing; first send creates a session and navigates to /chat/[id].
export default function NewChatScreen() {
  return <ChatConversation sessionId={null} />;
}
