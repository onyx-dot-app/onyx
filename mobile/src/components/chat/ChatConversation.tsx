// Shared by the new-chat landing (sessionId=null) and an open session (/chat/[id]).
import { useChatSessions } from "@/api/chat/sessions";
import { ChatScreen, CenteredContent } from "@/components/chat/ChatScreen";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";
import { InputBar } from "@/components/chat/InputBar";
import { MessageList } from "@/components/chat/MessageList";
import { WelcomeMessage } from "@/components/chat/WelcomeMessage";
import { useChatController } from "@/hooks/useChatController";

interface ChatConversationProps {
  sessionId: string | null;
}

export function ChatConversation({ sessionId }: ChatConversationProps) {
  const { messages, chatState, input, setInput, submit, stop } =
    useChatController(sessionId);
  const { sessions } = useChatSessions();

  const session = sessionId
    ? sessions.find((chatSession) => chatSession.id === sessionId)
    : undefined;
  // new chat has no title; opened session shows its name
  const title = sessionId
    ? session?.name && session.name.trim()
      ? session.name
      : UNNAMED_CHAT
    : undefined;

  return (
    <ChatScreen
      title={title}
      input={
        <InputBar
          value={input}
          onChangeText={setInput}
          onSend={() => {
            void submit();
          }}
          onStop={stop}
          chatState={chatState}
        />
      }
    >
      {messages.length === 0 ? (
        <CenteredContent>
          <WelcomeMessage />
        </CenteredContent>
      ) : (
        <MessageList messages={messages} />
      )}
    </ChatScreen>
  );
}
