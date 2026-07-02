// Shared by the new-chat landing (sessionId=null) and an open session (/chat/[id]).
import { useLocalSearchParams } from "expo-router";

import { useChatSessions } from "@/api/chat/sessions";
import { ChatScreen } from "@/components/chat/ChatScreen";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";
import { InputBar } from "@/components/chat/InputBar";
import { MessageList } from "@/components/chat/MessageList";
import { DEFAULT_AGENT_ID } from "@/chat/agents";
import { useChatController } from "@/hooks/useChatController";
import { useChatSessionController } from "@/hooks/useChatSessionController";
import { useLiveAgent } from "@/hooks/useLiveAgent";

interface ChatConversationProps {
  sessionId: string | null;
}

export function ChatConversation({ sessionId }: ChatConversationProps) {
  const { sessions } = useChatSessions();
  const { agentId: agentIdParam } = useLocalSearchParams<{
    agentId?: string;
  }>();

  const session = sessionId
    ? sessions.find((chatSession) => chatSession.id === sessionId)
    : undefined;

  // Landing: agent from the route param. Existing session: its creation-time persona wins.
  const selectedAgentId = agentIdParam != null ? Number(agentIdParam) : null;
  const liveAgent = useLiveAgent(
    Number.isNaN(selectedAgentId) ? null : selectedAgentId,
    session?.persona_id ?? null,
  );
  const personaId = liveAgent?.id ?? DEFAULT_AGENT_ID;
  const isDefaultAgent = liveAgent == null || liveAgent.id === DEFAULT_AGENT_ID;

  const { messages, chatState, input, setInput, submit, stop } =
    useChatController(sessionId, personaId);
  // re-attaches to an in-flight run when opened cold
  useChatSessionController(sessionId);

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
        <ChatEmptyState
          agent={liveAgent}
          isDefaultAgent={isDefaultAgent}
          onStarterSelect={(message) => {
            void submit(message);
          }}
        />
      ) : (
        <MessageList messages={messages} />
      )}
    </ChatScreen>
  );
}
