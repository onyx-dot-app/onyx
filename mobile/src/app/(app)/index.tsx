import { ChatScreen, CenteredContent } from "@/components/chat/ChatScreen";
import { WelcomeMessage } from "@/components/chat/WelcomeMessage";

// New-chat landing (mirrors web's centered WelcomeMessage empty state).
export default function NewChatScreen() {
  return (
    <ChatScreen>
      <CenteredContent>
        <WelcomeMessage />
      </CenteredContent>
    </ChatScreen>
  );
}
