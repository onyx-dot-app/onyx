import { useLocalSearchParams } from "expo-router";

import { ChatScreen, CenteredContent } from "@/components/chat/ChatScreen";
import { Text } from "@/components/ui/text";
import { useChatSessions } from "@/api/chat/sessions";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";

// Static scaffold; streaming + message rendering land in PR 3.
export default function ChatSessionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { sessions } = useChatSessions();
  const session = sessions.find((chatSession) => chatSession.id === id);
  const title =
    session?.name && session.name.trim() ? session.name : UNNAMED_CHAT;

  return (
    <ChatScreen title={title}>
      <CenteredContent>
        <Text font="main-content-body" color="text-03" className="text-center">
          Messages will appear here once sending is enabled.
        </Text>
      </CenteredContent>
    </ChatScreen>
  );
}
