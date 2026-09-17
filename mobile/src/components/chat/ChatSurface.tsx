import { ScrollView, StyleSheet, View } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
} from "react-native-reanimated";
import { router, useGlobalSearchParams, usePathname } from "expo-router";

import { useAgents } from "@/api/chat/agents";
import { useProjectDetails } from "@/api/chat/projects";
import { useChatSessions } from "@/api/chat/sessions";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { ChatScreen } from "@/components/chat/ChatScreen";
import { UNNAMED_CHAT } from "@/components/chat/ChatSessionList";
import { InputBar } from "@/components/chat/InputBar";
import { MessageList } from "@/components/chat/MessageList";
import { ProjectChatSessionList } from "@/components/chat/ProjectChatSessionList";
import { ProjectContextPanel } from "@/components/chat/ProjectContextPanel";
import { DEFAULT_AGENT_ID } from "@/chat/agents";
import { deriveFocus, type ChatFocus } from "@/chat/chatFocus";
import { useChatController } from "@/hooks/useChatController";
import { useChatSessionController } from "@/hooks/useChatSessionController";
import { useLiveAgent } from "@/hooks/useLiveAgent";
import { useComposerDraft } from "@/hooks/useComposerDraft";
import {
  ComposerToolsProvider,
  useComposerToolsState,
} from "@/state/ComposerToolsProvider";

const TRANSITION_MS = 150;

// Persistent overlay mounted in (app)/_layout: morphed in place by route→focus so
// header/composer never remount; null on non-chat routes (the Stack shows through).
export function ChatSurface() {
  const pathname = usePathname();
  const focus = deriveFocus(pathname);
  if (!focus) return null;
  return (
    <View style={StyleSheet.absoluteFill}>
      <ChatSurfaceContent focus={focus} />
    </View>
  );
}

// Never remounted across new↔chat↔project — only `focus` changes, so chrome/composer
// persist and the body cross-fades.
function ChatSurfaceContent({ focus }: { focus: ChatFocus }) {
  const sessionId = focus.kind === "chat" ? focus.sessionId : null;
  const projectId = focus.kind === "project" ? focus.projectId : null;
  const isProject = focus.kind === "project";

  const { sessions } = useChatSessions();
  const { agents } = useAgents();
  const { agentId: agentIdParam } = useGlobalSearchParams<{
    agentId?: string;
  }>();

  const session = sessionId
    ? sessions.find((chatSession) => chatSession.id === sessionId)
    : undefined;

  // Landing: agent from the route param. Existing session: its creation-time persona wins.
  const parsedAgentId = agentIdParam != null ? Number(agentIdParam) : NaN;
  // Only a non-negative integer id is honored; a bogus deep-link param (Infinity/float/negative)
  // falls back to the default persona.
  const selectedAgentId =
    Number.isInteger(parsedAgentId) && parsedAgentId >= 0
      ? parsedAgentId
      : null;
  // Which persona a *new* session would be created with. Deliberately resolved without any session
  // data: it is only read when `sessionId` is null, i.e. when there is no session to describe. That
  // is what keeps this off the cycle personaId → controller → hydrated persona → liveAgent.
  const creationAgent = useLiveAgent(selectedAgentId, null);
  // Project chats create with the default agent; new/chat honors the picked one.
  const personaId = isProject
    ? DEFAULT_AGENT_ID
    : (creationAgent?.id ?? selectedAgentId ?? DEFAULT_AGENT_ID);

  const {
    messages,
    chatState,
    submit,
    stop,
    isHydrating,
    conversationPersonaId,
  } = useChatController(sessionId, personaId, projectId);

  // The agent this conversation actually runs on. The sessions list omits project chats, so the
  // hydrated persona is the fallback authority — without it a project chat can never name its agent.
  const liveAgent = useLiveAgent(
    selectedAgentId,
    session?.persona_id ?? conversationPersonaId,
  );
  // Pairs with `liveAgent` in ChatEmptyState, so it describes the agent on screen rather than the
  // one a new session would be created with.
  const isDefaultAgent =
    (liveAgent?.id ?? selectedAgentId ?? DEFAULT_AGENT_ID) === DEFAULT_AGENT_ID;
  // re-attaches to an in-flight run when opened cold
  useChatSessionController(sessionId);

  // Per-conversation draft, keyed so navigation restores it and it can't leak across the
  // persistent composer.
  const draft = useComposerDraft(`${sessionId ?? "new"}:${projectId ?? ""}`);

  // null while the agent isn't knowable: until the session's persona is known (from the list or
  // from hydration), `liveAgent` falls back to the default agent, which would look like an agent
  // switch and re-gate the toolbar mid-conversation. `persona_id` is nullable, so a session row
  // alone is not proof of knowledge.
  const conversationPersonaKnown =
    session?.persona_id != null || conversationPersonaId != null;
  const conversationAgent =
    sessionId == null || conversationPersonaKnown ? liveAgent : null;
  // Project chats are always created with the default persona (see `personaId` above), so the tool
  // controls must describe that persona — not whichever agent the sidebar happens to have selected.
  // Otherwise the menu lists another agent's tools and a forced id from it kills the turn
  // server-side ("Forced tool N not found in tools").
  const composerAgent = isProject
    ? (agents.find((candidate) => candidate.id === personaId) ?? null)
    : conversationAgent;
  const composerTools = useComposerToolsState({
    chatSessionId: sessionId,
    agent: composerAgent,
    isProjectWorkflow: isProject,
    projectId,
  });

  const { data: details, isLoading } = useProjectDetails(projectId);
  const chats = details?.project?.chat_sessions ?? [];

  const title = isProject
    ? details?.project?.name
    : sessionId
      ? session?.name && session.name.trim()
        ? session.name
        : UNNAMED_CHAT
      : undefined;

  // Gate on hasBlockingFiles so a still-uploading file can't be sent; a starter keeps the text
  // (consumeAttachments), a send clears both.
  const sendWithAttachments = (message?: string) => {
    if (draft.hasBlockingFiles) return;
    const clearDraft =
      message == null ? draft.consume : draft.consumeAttachments;
    // Captured before the create await: picking a different agent while it is in flight must not
    // change what this session is recorded as running on.
    const sentWithAgent = composerAgent;
    submit(
      message ?? draft.text,
      draft.descriptors,
      () => {
        // `onAccepted` runs only once the session exists — a failed create throws before it — and
        // everything from here to the route change is synchronous. That makes it the one moment
        // we can say "this send created the session", which a null → non-null id alone cannot.
        if (sessionId == null) composerTools.notePendingSend(sentWithAgent);
        clearDraft();
      },
      composerTools.resolveToolOptions(),
    );
  };

  const composer = (
    <Animated.View layout={LinearTransition.duration(TRANSITION_MS)}>
      <InputBar
        value={draft.text}
        onChangeText={draft.setText}
        onSend={() => sendWithAttachments()}
        onStop={stop}
        chatState={chatState}
        attachments={draft}
      />
    </Animated.View>
  );

  const below = isProject ? (
    <Animated.View
      key="project-chats"
      entering={FadeIn.duration(TRANSITION_MS)}
      exiting={FadeOut.duration(TRANSITION_MS)}
      className="flex-1"
    >
      <ScrollView keyboardShouldPersistTaps="handled">
        <View className="px-24 pb-24 pt-8">
          <ProjectChatSessionList
            chats={chats}
            agents={agents}
            personaIdToFeatured={
              details?.persona_id_to_is_featured ?? undefined
            }
            isLoading={isLoading && !details}
            onSelect={(id) =>
              router.navigate({ pathname: "/chat/[id]", params: { id } })
            }
          />
        </View>
      </ScrollView>
    </Animated.View>
  ) : undefined;

  return (
    <ComposerToolsProvider value={composerTools}>
      <ChatScreen title={title} input={composer} below={below}>
        {isProject ? (
          <Animated.View
            key="project-context"
            entering={FadeIn.duration(TRANSITION_MS)}
            exiting={FadeOut.duration(TRANSITION_MS)}
            className="max-h-[50%]"
          >
            <ScrollView keyboardShouldPersistTaps="handled">
              <View className="gap-24 px-24 pb-8 pt-8">
                <ProjectContextPanel
                  projectId={projectId}
                  details={details}
                  isLoading={isLoading}
                />
              </View>
            </ScrollView>
          </Animated.View>
        ) : messages.length === 0 && !isHydrating ? (
          <Animated.View
            key="empty"
            entering={FadeIn.duration(TRANSITION_MS)}
            exiting={FadeOut.duration(TRANSITION_MS)}
            className="flex-1"
          >
            <ChatEmptyState
              agent={liveAgent}
              isDefaultAgent={isDefaultAgent}
              onStarterSelect={sendWithAttachments}
            />
          </Animated.View>
        ) : (
          <Animated.View
            key="messages"
            entering={FadeIn.duration(TRANSITION_MS)}
            exiting={FadeOut.duration(TRANSITION_MS)}
            className="flex-1"
          >
            <MessageList
              key={sessionId ?? "new"}
              messages={messages}
              agent={liveAgent}
            />
          </Animated.View>
        )}
      </ChatScreen>
    </ComposerToolsProvider>
  );
}
